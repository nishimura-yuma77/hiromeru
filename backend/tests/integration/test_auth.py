from httpx import AsyncClient

from services.context import ServiceContext
from tests.conftest import ORIGIN, PASSWORD, AccountFactory
from tests.support.client import Account
from tests.support.fakes import FixedClock


async def test_ログイン成功_正しい認証情報のとき200とCookie2種とcsrf_tokenを返す(
    anonymous: AsyncClient, account: Account
) -> None:
    response = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": account.email.upper(), "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["marketer_id"] == account.marketer_id
    assert data["email"] == account.email
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith("hiromeru_session=") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith("csrf_token=") and "HttpOnly" not in c for c in cookies)


async def test_ログイン失敗_パスワードが違うときと未登録のメールは同じ401(
    anonymous: AsyncClient, account: Account
) -> None:
    wrong_password = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": account.email, "password": "wrong"},
        headers={"Origin": ORIGIN},
    )
    unknown = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )

    assert wrong_password.status_code == unknown.status_code == 401
    assert wrong_password.json() == unknown.json()
    assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_ログインのOrigin検証_許可外のOriginのとき403(anonymous: AsyncClient) -> None:
    response = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "x"},
        headers={"Origin": "https://evil.example.com"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_ログインのBody検証_未定義フィールドがあるとき400(anonymous: AsyncClient) -> None:
    response = await anonymous.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "x", "company_id": 1},
        headers={"Origin": ORIGIN},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_ARGUMENT"


async def test_me_ログイン済みのとき自分の情報を返しcsrf_tokenは返さない(account: Account) -> None:
    response = await account.client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "marketer_id": account.marketer_id,
        "email": account.email,
    }


async def test_me_Cookieがないとき401でCookieを削除する(anonymous: AsyncClient) -> None:
    response = await anonymous.get("/api/v1/auth/me")

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "UNAUTHENTICATED"
    assert error["field_errors"] == []
    deleted = response.headers.get_list("set-cookie")
    assert any("hiromeru_session=" in c and "Max-Age=0" in c for c in deleted)
    assert any("csrf_token=" in c and "Max-Age=0" in c for c in deleted)


async def test_ログアウト_Cookieを削除し以後のmeは401(account: Account) -> None:
    response = await account.client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"success": True, "data": None, "error": None}
    assert (await account.client.get("/api/v1/auth/me")).status_code == 401


async def test_アイドル期限_8時間を超えて操作がないとき401(
    account: Account, clock: FixedClock
) -> None:
    clock.advance(8 * 3600 + 1)

    response = await account.client.get("/api/v1/auth/me")

    assert response.status_code == 401


async def test_Cookie再発行_期限内のAPI呼び出しでアイドル期限が延長される(
    account: Account, clock: FixedClock
) -> None:
    clock.advance(7 * 3600)
    assert (await account.client.get("/api/v1/auth/me")).status_code == 200
    clock.advance(7 * 3600)

    response = await account.client.get("/api/v1/auth/me")

    assert response.status_code == 200


async def test_絶対期限_7日を超えたとき操作を続けていても401(
    account: Account, clock: FixedClock
) -> None:
    response = await account.client.get("/api/v1/auth/me")
    for _ in range(23):
        clock.advance(8 * 3600 - 60)
        response = await account.client.get("/api/v1/auth/me")
        if response.status_code == 401:
            break

    assert response.status_code == 401


async def test_CSRF検証_トークンヘッダーがないとき状態変更APIは403(account: Account) -> None:
    account.client.headers.pop("X-CSRF-Token")

    response = await account.client.post("/api/v1/agent-sessions")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_VALIDATION_FAILED"


async def test_CSRF検証_他人のトークンのとき403(
    account: Account, new_account: AccountFactory
) -> None:
    other = await new_account()
    account.client.headers["X-CSRF-Token"] = other.csrf

    response = await account.client.post("/api/v1/agent-sessions")

    assert response.status_code == 403


async def test_CSRF検証_Originが許可外のとき403(account: Account) -> None:
    account.client.headers["Origin"] = "https://evil.example.com"

    response = await account.client.post("/api/v1/agent-sessions")

    assert response.status_code == 403


async def test_認証済みContext_他社の施策IDを指定しても404(
    account: Account, new_account: AccountFactory, ctx: ServiceContext
) -> None:
    del ctx
    other = await new_account()
    campaign_id = await other.create_campaign()

    response = await account.client.get(f"/api/v1/campaigns/{campaign_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CAMPAIGN_NOT_FOUND"
