import asyncio
import json
from urllib.parse import quote

from httpx import AsyncClient, Response

from core.masking import mask_text
from services.context import ServiceContext
from tests.conftest import AccountFactory
from tests.support.client import Account
from tests.support.fakes import FakeAgentRunner, FixedClock

TURNS = "/api/v1/agent-sessions/{}/turns"


async def _send(account: Account, session_id: int, message: str, **headers: str) -> Response:
    return await account.client.post(
        TURNS.format(session_id), json={"message": message}, headers=headers
    )


def _events(text: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    for block in text.split("\n\n"):
        lines = [line for line in block.splitlines() if not line.startswith(":")]
        if len(lines) == 2 and lines[0].startswith("event: "):
            events.append((lines[0][7:], json.loads(lines[1][6:])))
    return events


async def test_Session作成_201でsession_idを返しタイトルは空(account: Account) -> None:
    response = await account.client.post("/api/v1/agent-sessions")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["session_id"] > 0
    assert data["title"] is None


async def test_Session一覧_自分のSessionだけを更新日時の降順で返す(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    await other.create_session()
    first = await account.create_session()
    second = await account.create_session()

    response = await account.client.get("/api/v1/agent-sessions")

    assert [s["session_id"] for s in response.json()["data"]["sessions"]] == [second, first]


async def test_Session一覧のページング_limitとcursorで続きを取得できる(account: Account) -> None:
    ids = [await account.create_session() for _ in range(3)]

    page1 = (await account.client.get("/api/v1/agent-sessions?limit=2")).json()["data"]
    page2 = (
        await account.client.get(
            f"/api/v1/agent-sessions?limit=2&cursor={quote(page1['next_cursor'])}"
        )
    ).json()["data"]

    assert [s["session_id"] for s in page1["sessions"]] == [ids[2], ids[1]]
    assert [s["session_id"] for s in page2["sessions"]] == [ids[0]]
    assert page2["next_cursor"] is None


async def test_メッセージ送信_JSON_201でTurnとAgentの回答を返す(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    agent.reply = "提案です"

    response = await _send(account, session_id, "春のキャンペーンを考えて")

    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["kind"] == "chat"
    assert data["turn_number"] == 1
    assert [item["type"] for item in data["items"]] == ["user_message", "assistant_message"]
    assert data["items"][0]["content"] == {"text": "春のキャンペーンを考えて"}
    assert data["items"][1]["content"] == {"text": "提案です"}
    assert agent.inputs[0].company_id == account.company_id


async def test_タイトル_最初のメッセージの先頭50文字がマスクされて設定される(
    account: Account,
) -> None:
    session_id = await account.create_session()
    message = "連絡先は taro@example.com です。" + "あ" * 80

    await _send(account, session_id, message)

    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()["data"]
    title = history["session"]["title"]
    assert title == mask_text(message)[:50]
    assert "taro@example.com" not in title


async def test_メッセージのマスク_履歴のuser_messageにメールアドレスの生値が残らない(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()

    await _send(account, session_id, "taro@example.com に連絡")

    history = await account.client.get(f"/api/v1/agent-sessions/{session_id}")
    assert "taro@example.com" not in history.text
    assert "taro@example.com" not in agent.inputs[0].message


async def test_メッセージ検証_空のとき400でTurnを作らない(account: Account) -> None:
    session_id = await account.create_session()

    response = await _send(account, session_id, "   ")

    assert response.status_code == 400
    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()["data"]
    assert history["turns"] == []


async def test_メッセージ検証_上限を超えるとき400(account: Account) -> None:
    session_id = await account.create_session()

    response = await _send(account, session_id, "あ" * 4001)

    assert response.status_code == 400


async def test_メッセージ送信_他人のSessionのとき404(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    other_session = await other.create_session()

    response = await _send(account, other_session, "こんにちは")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_SESSION_NOT_FOUND"


async def test_Turn番号_連続して送るとturn_numberが増える(account: Account) -> None:
    session_id = await account.create_session()

    await _send(account, session_id, "1回目")
    second = await _send(account, session_id, "2回目")

    assert second.json()["data"]["turn_number"] == 2


async def test_Agent失敗_実行が例外のときturnはfailedで500_AGENT_EXECUTION_FAILED(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    agent.error = RuntimeError("secret detail sk-abc")

    response = await _send(account, session_id, "こんにちは")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "AGENT_EXECUTION_FAILED"
    assert error["agent_turn_id"] is not None
    assert "secret detail" not in response.text
    turn = await account.client.get(
        f"/api/v1/agent-sessions/{session_id}/turns/{error['agent_turn_id']}"
    )
    assert turn.json()["data"]["status"] == "failed"
    assert turn.json()["data"]["error"]["code"] == "AGENT_EXECUTION_FAILED"


async def test_時間制限_上限を超えたときturnはfailedで504_TURN_TIME_LIMIT_EXCEEDED(
    account: Account, agent: FakeAgentRunner, ctx: ServiceContext
) -> None:
    session_id = await account.create_session()
    agent.hang = True
    ctx.settings.turn_time_limit_seconds = 0.05

    response = await _send(account, session_id, "こんにちは")

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "TURN_TIME_LIMIT_EXCEEDED"


async def test_実行中のTurn_処理中に別のメッセージを送ると409_TURN_IN_PROGRESS(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    agent.gate = asyncio.Event()
    running = asyncio.create_task(_send(account, session_id, "1つ目"))
    await asyncio.wait_for(agent.started.wait(), 5)

    second = await _send(account, session_id, "2つ目")
    agent.gate.set()
    first = await running

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "TURN_IN_PROGRESS"
    assert first.status_code == 201


async def test_中断Turnの復旧_330秒を超えたrunningのTurnはfailedにして新しいTurnを開始できる(
    account: Account, agent: FakeAgentRunner, clock: FixedClock
) -> None:
    session_id = await account.create_session()
    agent.gate = asyncio.Event()
    stale = asyncio.create_task(_send(account, session_id, "中断される"))
    await asyncio.wait_for(agent.started.wait(), 5)
    clock.advance(331)
    agent.gate = None

    response = await _send(account, session_id, "再送")

    assert response.status_code == 201
    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()["data"]
    first_turn = history["turns"][0]
    assert first_turn["status"] == "failed"
    assert first_turn["error"]["code"] == "TURN_INTERRUPTED"
    stale.cancel()
    await asyncio.gather(stale, return_exceptions=True)


async def test_Turn取得_自分のTurnのとき200で他人のSessionは404(
    account: Account, new_account: AccountFactory
) -> None:
    session_id = await account.create_session()
    turn_id = (await _send(account, session_id, "こんにちは")).json()["data"]["agent_turn_id"]
    other = await new_account()

    mine = await account.client.get(f"/api/v1/agent-sessions/{session_id}/turns/{turn_id}")
    theirs = await other.client.get(f"/api/v1/agent-sessions/{session_id}/turns/{turn_id}")
    missing = await account.client.get(f"/api/v1/agent-sessions/{session_id}/turns/999999999")

    assert mine.status_code == 200
    assert theirs.status_code == 404
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "AGENT_TURN_NOT_FOUND"


async def test_履歴のページング_before_turn_numberより前のTurnを返す(account: Account) -> None:
    session_id = await account.create_session()
    for n in range(3):
        await _send(account, session_id, f"{n}回目")

    latest = (await account.client.get(f"/api/v1/agent-sessions/{session_id}?limit=2")).json()[
        "data"
    ]
    earlier = (
        await account.client.get(
            f"/api/v1/agent-sessions/{session_id}?limit=2&before_turn_number=2"
        )
    ).json()["data"]

    assert [t["turn_number"] for t in latest["turns"]] == [2, 3]
    assert latest["has_more"] is True
    assert [t["turn_number"] for t in earlier["turns"]] == [1]
    assert earlier["has_more"] is False


async def test_履歴_承認APIの実行Turnも同じSessionに残る(account: Account) -> None:
    session_id = await account.create_session()
    await account.create_campaign(session_id)

    history = (await account.client.get(f"/api/v1/agent-sessions/{session_id}")).json()["data"]

    assert [t["kind"] for t in history["turns"]] == ["approval"]
    items = history["turns"][0]["items"]
    assert [item["type"] for item in items] == ["approval_action", "api_result"]
    assert items[0]["content"]["type"] == "upsert_campaign"
    assert items[1]["content"]["success"] is True


async def test_SSE_Accept指定のときturn_startedからturn_finishedまで進捗を返す(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    agent.activities = [("tool", "search_campaigns")]

    response = await account.client.post(
        TURNS.format(session_id),
        json={"message": "検索して"},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [name for name, _ in events] == [
        "turn_started",
        "activity_started",
        "activity_finished",
        "turn_finished",
    ]
    assert events[1][1]["name"] == "search_campaigns"
    finished = events[-1][1]
    assert finished["status"] == "completed"


async def test_SSE_Agent失敗のときturn_finishedのstatusがfailed(
    account: Account, agent: FakeAgentRunner
) -> None:
    session_id = await account.create_session()
    agent.error = RuntimeError("boom")

    response = await account.client.post(
        TURNS.format(session_id),
        json={"message": "失敗させる"},
        headers={"Accept": "text/event-stream"},
    )

    events = _events(response.text)
    assert events[-1][0] == "turn_finished"
    assert events[-1][1]["status"] == "failed"


async def test_SSE_Turnを開始できないときはSSEではなくJSONのエラーを返す(
    account: Account, anonymous: AsyncClient
) -> None:
    del anonymous

    response = await account.client.post(
        TURNS.format(999999999),
        json={"message": "こんにちは"},
        headers={"Accept": "text/event-stream"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_SESSION_NOT_FOUND"
