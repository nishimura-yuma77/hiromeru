"""自社ユーザー管理・招待API（API_DESIGN 11.2、11.3）。SESはFakeへ差し替える。"""

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AsyncExitStack
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from domain.enums import EmailStatus, UserStatus
from models import Admin, Campaign, Email, Invitation, User
from repositories.database import SessionLocal
from tests.conftest import ORIGIN, PASSWORD, AccountFactory, login_client
from tests.support.client import Account
from tests.support.db import create_company, create_user
from tests.support.fakes import FakeEmail, FixedClock

NEW_PASSWORD = "Invited-Passw0rd!"

type AdminFactory = Callable[..., Coroutine[Any, Any, Account]]


@pytest.fixture
async def new_admin(app: FastAPI) -> AsyncIterator[AdminFactory]:
    """管理ユーザーとしてログインしたクライアントを作る。既定は新しい会社の責任者。"""
    stack = AsyncExitStack()

    async def create(company_id: int | None = None, *, responsible: bool = True) -> Account:
        company = company_id if company_id is not None else await create_company()
        email = f"{uuid.uuid4().hex}@example.com"
        user_id = await create_user(
            company, email, PASSWORD, name="責任者", admin=True, responsible=responsible
        )
        client, csrf = await login_client(stack, app, email, PASSWORD, admin=True)
        return Account(client, user_id, company, email, csrf)

    yield create
    await stack.aclose()


@pytest.fixture
async def admin(new_admin: AdminFactory) -> Account:
    return await new_admin()


async def _invite(
    admin: Account, *, user_type: str = "marketer", email: str | None = None
) -> tuple[int, str]:
    address = email or f"{uuid.uuid4().hex}@example.com"
    response = await admin.client.post(
        "/api/v1/admin/users",
        json={"user_type": user_type, "name": "招待者", "email": address},
    )
    assert response.status_code == 201, response.text
    return int(response.json()["data"]["user_id"]), address


async def _accept(client: AsyncClient, token: str, password: str = NEW_PASSWORD) -> Any:
    return await client.post(
        "/api/v1/invitation-acceptances",
        json={"token": token, "password": password},
        headers={"Origin": ORIGIN},
    )


async def _user(user_id: int) -> User:
    async with SessionLocal() as session:
        return (await session.execute(select(User).where(User.id == user_id))).scalar_one()


async def _emails(user_id: int) -> list[Email]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(Email).where(Email.user_id == user_id).order_by(Email.id)
        )
        return list(rows.scalars())


async def _invitations(user_id: int) -> list[Invitation]:
    async with SessionLocal() as session:
        rows = await session.execute(
            select(Invitation).where(Invitation.user_id == user_id).order_by(Invitation.id)
        )
        return list(rows.scalars())


# 権限・会社境界


async def test_権限_マーケターユーザーは管理APIで403_ADMIN_FORBIDDEN(account: Account) -> None:
    listed = await account.client.get("/api/v1/admin/users")
    invited = await account.client.post(
        "/api/v1/admin/users",
        json={"user_type": "marketer", "name": "x", "email": "x@example.com"},
    )

    assert listed.status_code == invited.status_code == 403
    assert listed.json()["error"]["code"] == "ADMIN_FORBIDDEN"
    assert invited.json()["error"]["code"] == "ADMIN_FORBIDDEN"


async def test_権限_未ログインは401(anonymous: AsyncClient) -> None:
    response = await anonymous.get("/api/v1/admin/users")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


async def test_権限_状態変更APIはCSRF検証を行う(admin: Account) -> None:
    admin.client.headers.pop("X-CSRF-Token")

    response = await admin.client.post(
        "/api/v1/admin/users",
        json={"user_type": "marketer", "name": "x", "email": "x@example.com"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_会社境界_他社のユーザーと存在しないユーザーは同じ404(
    admin: Account, new_admin: AdminFactory
) -> None:
    other = await new_admin()
    responses = [
        await admin.client.patch(f"/api/v1/admin/users/{user_id}", json={"name": "変更"})
        for user_id in (other.user_id, 999_999_999)
    ]
    suspended = await admin.client.post(f"/api/v1/admin/users/{other.user_id}/suspensions")

    assert [r.status_code for r in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()
    assert suspended.status_code == 404
    assert (await _user(other.user_id)).name == "責任者"


async def test_会社境界_一覧は自社のユーザーだけを返す(
    admin: Account, new_admin: AdminFactory
) -> None:
    await new_admin()
    await _invite(admin)

    response = await admin.client.get("/api/v1/admin/users")

    users = response.json()["data"]["users"]
    assert {user["user_id"] for user in users} >= {admin.user_id}
    async with SessionLocal() as session:
        companies = set(
            (
                await session.execute(
                    select(User.company_id).where(User.id.in_([u["user_id"] for u in users]))
                )
            ).scalars()
        )
    assert companies == {admin.company_id}


# 一覧


async def test_一覧_責任者は送信状態nullで返し内部情報は返さない(admin: Account) -> None:
    response = await admin.client.get("/api/v1/admin/users")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["page"] == 1 and data["page_size"] == 20
    assert data["total_count"] == 1 and data["total_pages"] == 1
    assert data["users"] == [
        {
            "user_id": admin.user_id,
            "name": "責任者",
            "email": admin.email,
            "user_type": "admin",
            "status": "active",
            "is_responsible": True,
            "email_status": None,
        }
    ]


async def test_一覧_20件ずつ新しい順で範囲外のpageは400(admin: Account, clock: FixedClock) -> None:
    for _ in range(20):
        clock.advance(1)
        await _invite(admin)

    first = (await admin.client.get("/api/v1/admin/users?page=1")).json()["data"]
    second = (await admin.client.get("/api/v1/admin/users?page=2")).json()["data"]
    beyond = await admin.client.get("/api/v1/admin/users?page=3")
    zero = await admin.client.get("/api/v1/admin/users?page=0")
    text = await admin.client.get("/api/v1/admin/users?page=abc")

    assert (first["total_count"], first["total_pages"]) == (21, 2)
    assert len(first["users"]) == 20 and len(second["users"]) == 1
    assert second["users"][0]["user_id"] == admin.user_id
    ids = [user["user_id"] for user in first["users"]]
    assert ids == sorted(ids, reverse=True)
    assert {beyond.status_code, zero.status_code, text.status_code} == {400}
    assert beyond.json()["error"]["code"] == "INVALID_ARGUMENT"


# 新規招待とSES


async def test_招待_招待中ユーザーとリンクを作り受付成功なら201(
    admin: Account, email: FakeEmail
) -> None:
    user_id, address = await _invite(admin, user_type="admin")

    user = await _user(user_id)
    assert (user.status, user.password, user.company_id) == (
        UserStatus.INVITED,
        None,
        admin.company_id,
    )
    [sent] = await _emails(user_id)
    assert (sent.status, sent.attempt_count) == (EmailStatus.ACCEPTED, 1)
    assert sent.ses_message_id is not None
    [invitation] = await _invitations(user_id)
    token = email.last_token()
    assert invitation.token_hash != token and token not in invitation.token_hash
    assert email.sent[-1].to == address
    async with SessionLocal() as session:
        assert await session.scalar(select(Admin.id).where(Admin.user_id == user_id)) is not None


async def test_招待_メールアドレスは小文字に正規化し他社で使用中でも同じ409(
    admin: Account, new_admin: AdminFactory, email: FakeEmail
) -> None:
    other = await new_admin()

    response = await admin.client.post(
        "/api/v1/admin/users",
        json={"user_type": "marketer", "name": "重複", "email": f"  {other.email.upper()} "},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_INVITATION_CONFLICT"
    assert email.sent == []


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"user_type": "marketer", "email": "a@example.com"}, "name", "REQUIRED"),
        ({"user_type": "marketer", "name": "  ", "email": "a@example.com"}, "name", "REQUIRED"),
        (
            {"user_type": "marketer", "name": "x" * 256, "email": "a@example.com"},
            "name",
            "TOO_LONG",
        ),
        (
            {"user_type": "marketer", "name": "x", "email": "not-an-email"},
            "email",
            "INVALID_FORMAT",
        ),
        (
            {"user_type": "owner", "name": "x", "email": "a@example.com"},
            "user_type",
            "INVALID_FORMAT",
        ),
    ],
)
async def test_招待_入力不正は400でfield_errorsを返す(
    admin: Account, body: dict[str, str], field: str, code: str
) -> None:
    response = await admin.client.post("/api/v1/admin/users", json=body)

    assert response.status_code == 400
    errors = response.json()["error"]["field_errors"]
    assert {"field": field, "code": code} in [
        {"field": e["field"], "code": e["code"]} for e in errors
    ]


async def test_SES_スロットリングは同じリンクで最大2回再試行し受付成功なら201(
    admin: Account, email: FakeEmail
) -> None:
    email.outcomes = ["throttled", "throttled", "ok"]

    user_id, _ = await _invite(admin)

    [sent] = await _emails(user_id)
    assert (sent.status, sent.attempt_count, sent.last_error_code) == (
        EmailStatus.ACCEPTED,
        3,
        None,
    )
    assert len(email.sent) == 3 and len({m.body for m in email.sent}) == 1
    assert len(await _invitations(user_id)) == 1


@pytest.mark.parametrize(
    ("outcomes", "http_status", "code", "email_status", "attempts"),
    [
        (["throttled"] * 3, 502, "INVITATION_SEND_FAILED", EmailStatus.FAILED, 3),
        (["rejected"], 502, "INVITATION_SEND_FAILED", EmailStatus.FAILED, 1),
        (["unknown"], 504, "INVITATION_SEND_OUTCOME_UNKNOWN", EmailStatus.OUTCOME_UNKNOWN, 1),
    ],
)
async def test_SES_送信失敗と結果不明でもユーザーとリンクを残す(
    admin: Account,
    email: FakeEmail,
    outcomes: list[str],
    http_status: int,
    code: str,
    email_status: EmailStatus,
    attempts: int,
) -> None:
    email.outcomes = list(outcomes)
    address = f"{uuid.uuid4().hex}@example.com"

    response = await admin.client.post(
        "/api/v1/admin/users", json={"user_type": "marketer", "name": "招待者", "email": address}
    )

    assert response.status_code == http_status
    assert response.json()["error"]["code"] == code
    listed = (await admin.client.get("/api/v1/admin/users")).json()["data"]["users"]
    [target] = [user for user in listed if user["email"] == address]
    assert target["status"] == "invited" and target["email_status"] == email_status.value
    [sent] = await _emails(target["user_id"])
    assert (sent.status, sent.attempt_count) == (email_status, attempts)
    assert sent.last_error_code is not None
    assert len(email.sent) == attempts
    # 送信結果にかかわらず、発行済みリンクは有効のまま残る。
    accepted = await _accept(admin.client, email.last_token())
    assert accepted.status_code == 200


async def test_SES_想定外の例外ではpendingのまま残し500(admin: Account, email: FakeEmail) -> None:
    email.outcomes = ["unexpected"]
    address = f"{uuid.uuid4().hex}@example.com"

    response = await admin.client.post(
        "/api/v1/admin/users", json={"user_type": "marketer", "name": "招待者", "email": address}
    )

    assert response.status_code == 500
    listed = (await admin.client.get("/api/v1/admin/users")).json()["data"]["users"]
    [target] = [user for user in listed if user["email"] == address]
    assert target["email_status"] == "pending"


# 招待からのパスワード設定


async def test_受諾_パスワードを設定するとactiveになり種別のログイン画面から入れる(
    admin: Account, email: FakeEmail, anonymous: AsyncClient
) -> None:
    user_id, address = await _invite(admin)

    response = await _accept(anonymous, email.last_token())

    assert response.status_code == 200
    assert response.json()["data"] == {"user_type": "marketer"}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert (await _user(user_id)).status == UserStatus.ACTIVE
    login = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": address, "password": NEW_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    [invitation] = await _invitations(user_id)
    assert invitation.used_at is not None


async def test_受諾_使用済みリンクは理由を区別しない400(
    admin: Account, email: FakeEmail, anonymous: AsyncClient
) -> None:
    await _invite(admin)
    token = email.last_token()
    assert (await _accept(anonymous, token)).status_code == 200

    reused = await _accept(anonymous, token)
    unknown = await _accept(anonymous, "unknown-token")

    assert reused.status_code == unknown.status_code == 400
    assert reused.json() == unknown.json()
    assert reused.json()["error"]["code"] == "INVITATION_LINK_INVALID"


async def test_受諾_発行から1時間で期限切れになる(
    admin: Account, email: FakeEmail, anonymous: AsyncClient, clock: FixedClock
) -> None:
    await _invite(admin)
    clock.advance(3600)

    response = await _accept(anonymous, email.last_token())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVITATION_LINK_INVALID"


async def test_受諾_期限の直前なら設定できる(
    admin: Account, email: FakeEmail, anonymous: AsyncClient, clock: FixedClock
) -> None:
    await _invite(admin)
    clock.advance(3599)

    assert (await _accept(anonymous, email.last_token())).status_code == 200


async def test_受諾_パスワード条件違反ではリンクを消費しない(
    admin: Account, email: FakeEmail, anonymous: AsyncClient
) -> None:
    await _invite(admin)
    token = email.last_token()

    weak = await _accept(anonymous, token, "weakpassword")

    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert weak.json()["error"]["field_errors"][0]["field"] == "password"
    assert weak.json()["error"]["field_errors"][0]["code"] == "INVALID_FORMAT"
    assert (await _accept(anonymous, token)).status_code == 200


async def test_受諾_無効なリンクではパスワードの内容にかかわらずLINK_INVALID(
    anonymous: AsyncClient,
) -> None:
    response = await _accept(anonymous, "unknown-token", "weak")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVITATION_LINK_INVALID"


async def test_受諾_トークン欠落は400_REQUIREDで許可外Originは403(
    anonymous: AsyncClient,
) -> None:
    missing = await anonymous.post(
        "/api/v1/invitation-acceptances",
        json={"password": NEW_PASSWORD},
        headers={"Origin": ORIGIN},
    )
    evil = await anonymous.post(
        "/api/v1/invitation-acceptances",
        json={"token": "t", "password": NEW_PASSWORD},
        headers={"Origin": "https://evil.example.com"},
    )

    assert missing.status_code == 400
    assert missing.json()["error"]["field_errors"][0] == {
        "field": "token",
        "code": "REQUIRED",
        "message": "招待トークンを入力してください。",
    }
    assert evil.status_code == 403
    assert evil.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


# 再送


async def test_再送_古いリンクを無効化して新しいリンクを送る(
    admin: Account, email: FakeEmail, anonymous: AsyncClient
) -> None:
    user_id, _ = await _invite(admin)
    old_token = email.last_token()

    response = await admin.client.post(f"/api/v1/admin/users/{user_id}/invitations")

    assert response.status_code == 201
    assert response.json()["data"] == {"email_status": "accepted"}
    new_token = email.last_token()
    assert new_token != old_token
    assert (await _accept(anonymous, old_token)).status_code == 400
    assert (await _accept(anonymous, new_token)).status_code == 200
    first, second = await _invitations(user_id)
    assert first.invalidated_at is not None and second.used_at is not None
    assert len(await _emails(user_id)) == 2


async def test_再送_期限切れのリンクも明示的に無効化してから新しいリンクを作る(
    admin: Account, email: FakeEmail, clock: FixedClock
) -> None:
    user_id, _ = await _invite(admin)
    clock.advance(7200)

    response = await admin.client.post(f"/api/v1/admin/users/{user_id}/invitations")

    assert response.status_code == 201
    first, second = await _invitations(user_id)
    assert first.invalidated_at is not None and second.invalidated_at is None
    assert len(email.sent) == 2


async def test_再送_招待中以外には送らず409(
    admin: Account, account_in_admin_company: Account, email: FakeEmail
) -> None:
    response = await admin.client.post(
        f"/api/v1/admin/users/{account_in_admin_company.user_id}/invitations"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_STATE_CONFLICT"
    assert email.sent == []


@pytest.fixture
async def account_in_admin_company(admin: Account, app: FastAPI) -> AsyncIterator[Account]:
    """管理ユーザーと同じ会社の、ログイン済みのマーケターユーザー。"""
    address = f"{uuid.uuid4().hex}@example.com"
    user_id = await create_user(admin.company_id, address, PASSWORD, name="同僚")
    async with AsyncExitStack() as stack:
        client, csrf = await login_client(stack, app, address, PASSWORD)
        yield Account(client, user_id, admin.company_id, address, csrf)


# 利用停止・再開


async def test_停止_既存Cookieを即時401にし未使用リンクを無効化する(
    admin: Account, account_in_admin_company: Account
) -> None:
    target = account_in_admin_company
    assert (await target.client.get("/api/v1/auth/me")).status_code == 200

    response = await admin.client.post(f"/api/v1/admin/users/{target.user_id}/suspensions")

    assert response.status_code == 200
    assert response.json()["data"]["user"]["status"] == "suspended"
    assert (await target.client.get("/api/v1/auth/me")).status_code == 401
    user = await _user(target.user_id)
    assert (user.password, user.auth_generation) == (None, 1)


async def test_停止_招待中ユーザーの未使用リンクは使えなくなる(
    admin: Account, email: FakeEmail, anonymous: AsyncClient
) -> None:
    user_id, _ = await _invite(admin)

    await admin.client.post(f"/api/v1/admin/users/{user_id}/suspensions")

    assert (await _accept(anonymous, email.last_token())).status_code == 400


async def test_停止_本人と責任者は停止できず停止済みへの停止は200で変更しない(
    admin: Account, new_admin: AdminFactory, account_in_admin_company: Account
) -> None:
    other_admin = await new_admin(admin.company_id, responsible=False)
    target = account_in_admin_company

    myself = await admin.client.post(f"/api/v1/admin/users/{admin.user_id}/suspensions")
    responsible = await other_admin.client.post(f"/api/v1/admin/users/{admin.user_id}/suspensions")
    await admin.client.post(f"/api/v1/admin/users/{target.user_id}/suspensions")
    again = await admin.client.post(f"/api/v1/admin/users/{target.user_id}/suspensions")

    assert myself.status_code == responsible.status_code == 409
    assert myself.json()["error"]["code"] == "USER_SUSPENSION_FORBIDDEN"
    assert responsible.json()["error"]["code"] == "USER_SUSPENSION_FORBIDDEN"
    assert again.status_code == 200
    assert (await _user(target.user_id)).auth_generation == 1


async def test_再開_招待中へ戻して新しいリンクを送り旧パスワードでは入れない(
    admin: Account,
    account_in_admin_company: Account,
    email: FakeEmail,
    anonymous: AsyncClient,
) -> None:
    target = account_in_admin_company
    await admin.client.post(f"/api/v1/admin/users/{target.user_id}/suspensions")

    response = await admin.client.post(f"/api/v1/admin/users/{target.user_id}/reactivations")

    assert response.status_code == 200
    user = response.json()["data"]["user"]
    assert (user["status"], user["email_status"]) == ("invited", "accepted")
    assert (await _user(target.user_id)).auth_generation == 2
    old_login = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": target.email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert old_login.status_code == 401
    assert (await target.client.get("/api/v1/auth/me")).status_code == 401
    assert (await _accept(anonymous, email.last_token())).status_code == 200


async def test_再開_利用中は409で招待中は200のままメールを送らない(
    admin: Account, account_in_admin_company: Account, email: FakeEmail
) -> None:
    active = await admin.client.post(
        f"/api/v1/admin/users/{account_in_admin_company.user_id}/reactivations"
    )
    user_id, _ = await _invite(admin)
    sent = len(email.sent)
    invited = await admin.client.post(f"/api/v1/admin/users/{user_id}/reactivations")

    assert active.status_code == 409
    assert active.json()["error"]["code"] == "USER_STATE_CONFLICT"
    assert invited.status_code == 200
    assert invited.json()["data"]["user"]["email_status"] == "accepted"
    assert len(email.sent) == sent


# 表示名・ユーザー種別


async def test_種別変更_昇格で旧Cookieを失効させ会話履歴を維持する(
    admin: Account, account_in_admin_company: Account, app: FastAPI
) -> None:
    target = account_in_admin_company
    session_id = await target.create_session()

    response = await admin.client.patch(
        f"/api/v1/admin/users/{target.user_id}", json={"user_type": "admin", "name": "昇格"}
    )

    assert response.status_code == 200
    user = response.json()["data"]["user"]
    assert (user["user_type"], user["name"], user["is_responsible"]) == ("admin", "昇格", False)
    assert (await target.client.get("/api/v1/auth/me")).status_code == 401
    async with AsyncExitStack() as stack:
        client, _ = await login_client(stack, app, target.email, PASSWORD, admin=True)
        sessions = (await client.get("/api/v1/agent-sessions")).json()["data"]
        assert session_id in [item["session_id"] for item in sessions["sessions"]]
        me = (await client.get("/api/v1/auth/me")).json()["data"]
        assert (me["user_id"], me["is_admin"]) == (target.user_id, True)


async def test_種別変更_降格でadminsを削除しマーケター用の入口から入れる(
    admin: Account, new_admin: AdminFactory, anonymous: AsyncClient
) -> None:
    other = await new_admin(admin.company_id, responsible=False)

    response = await admin.client.patch(
        f"/api/v1/admin/users/{other.user_id}", json={"user_type": "marketer"}
    )

    assert response.status_code == 200
    assert (await other.client.get("/api/v1/admin/users")).status_code == 401
    login = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": other.email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    assert (await _user(other.user_id)).auth_generation == 1


async def test_種別変更_本人と責任者は409で同時指定の表示名も変えない(
    admin: Account, new_admin: AdminFactory
) -> None:
    other = await new_admin(admin.company_id, responsible=False)

    myself = await other.client.patch(
        f"/api/v1/admin/users/{other.user_id}", json={"user_type": "marketer", "name": "変更"}
    )
    responsible = await other.client.patch(
        f"/api/v1/admin/users/{admin.user_id}", json={"user_type": "marketer", "name": "変更"}
    )

    assert myself.status_code == responsible.status_code == 409
    assert myself.json()["error"]["code"] == "USER_ROLE_CHANGE_FORBIDDEN"
    assert responsible.json()["error"]["code"] == "USER_ROLE_CHANGE_FORBIDDEN"
    assert (await _user(other.user_id)).name == "責任者"
    assert (await _user(admin.user_id)).name == "責任者"


async def test_種別変更_招待中と停止中は409_USER_STATE_CONFLICT(admin: Account) -> None:
    user_id, _ = await _invite(admin)

    response = await admin.client.patch(
        f"/api/v1/admin/users/{user_id}", json={"user_type": "admin", "name": "変更"}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_STATE_CONFLICT"
    assert (await _user(user_id)).name == "招待者"


async def test_表示名_本人や招待中も編集でき種別が同じなら世代を更新しない(
    admin: Account,
) -> None:
    user_id, _ = await _invite(admin)

    own = await admin.client.patch(
        f"/api/v1/admin/users/{admin.user_id}", json={"name": "  新しい名前 ", "user_type": "admin"}
    )
    invited = await admin.client.patch(f"/api/v1/admin/users/{user_id}", json={"name": "招待2"})

    assert own.status_code == invited.status_code == 200
    assert own.json()["data"]["user"]["name"] == "新しい名前"
    assert (await _user(admin.user_id)).auth_generation == 0
    assert (await admin.client.get("/api/v1/auth/me")).status_code == 200
    assert invited.json()["data"]["user"]["name"] == "招待2"


async def test_表示名_両方の項目がないときと空文字は400(admin: Account) -> None:
    empty = await admin.client.patch(f"/api/v1/admin/users/{admin.user_id}", json={})
    blank = await admin.client.patch(f"/api/v1/admin/users/{admin.user_id}", json={"name": ""})
    path = await admin.client.patch("/api/v1/admin/users/0", json={"name": "x"})

    assert empty.status_code == blank.status_code == path.status_code == 400
    assert blank.json()["error"]["field_errors"][0]["code"] == "REQUIRED"


async def test_会話履歴_同じ会社の管理ユーザーにも他人の会話は見せない(
    admin: Account, account_in_admin_company: Account
) -> None:
    session_id = await account_in_admin_company.create_session()

    response = await admin.client.get(f"/api/v1/agent-sessions/{session_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "AGENT_SESSION_NOT_FOUND"


async def test_マーケター向け機能_管理ユーザーも本人のuser_idで施策を作れる(
    admin: Account, new_account: AccountFactory
) -> None:
    del new_account
    campaign_id = await admin.create_campaign()

    async with SessionLocal() as session:
        creator = await session.scalar(
            select(Campaign.created_by_user_id).where(Campaign.id == campaign_id)
        )
    assert creator == admin.user_id
