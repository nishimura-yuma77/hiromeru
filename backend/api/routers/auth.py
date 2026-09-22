"""認証API（API_DESIGN 2.9）。"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.cookies import csrf_cookie, deletion_cookies, session_cookie
from api.deps import Authenticated, Context, verify_origin
from api.request_body import read_json_body
from api.responses import ok
from core.security import issue_csrf_token, issue_session_token
from domain.requests import LoginRequest
from services.auth_service import AuthService
from services.validation import parse_json_object, validate_model

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", dependencies=[Depends(verify_origin)])
async def login(request: Request, ctx: Context) -> JSONResponse:
    """メールアドレスとパスワードを検証し、認証Cookieと `csrf_token` Cookieを発行する。

    ログインは `csrf_token` Cookieをまだ持たないため、Origin検証だけを適用する。
    """
    body = validate_model(LoginRequest, parse_json_object(await read_json_body(request)))
    marketer = await AuthService(ctx).login(body.email, body.password)
    now = ctx.clock.now()
    session_token, idle_expires_at = issue_session_token(
        ctx.settings.auth_secret(), marketer.marketer_id, now, now
    )
    csrf_token = issue_csrf_token(ctx.settings.auth_secret(), marketer.marketer_id)
    response = ok(
        {"marketer_id": marketer.marketer_id, "email": marketer.email, "csrf_token": csrf_token}
    )
    response.headers.append(
        "set-cookie", session_cookie(ctx.settings, session_token, idle_expires_at, now)
    )
    response.headers.append("set-cookie", csrf_cookie(ctx.settings, csrf_token))
    return response


@router.post("/logout", dependencies=[Depends(verify_origin)])
async def logout(ctx: Context) -> JSONResponse:
    """認証Cookieと `csrf_token` Cookieを削除する。未ログインでも同じ結果を返す。"""
    response = ok(None)
    for value in deletion_cookies(ctx.settings):
        response.headers.append("set-cookie", value)
    return response


@router.get("/me")
async def me(auth: Authenticated) -> JSONResponse:
    """ログイン中のマーケターの情報を返す。`csrf_token` は返さない。"""
    return ok({"marketer_id": auth.marketer_id, "email": auth.email})


@router.post("/csrf")
async def reissue_csrf(request: Request, ctx: Context, auth: Authenticated) -> JSONResponse:
    """認証とOriginを検証し、現在のマーケター用CSRF Tokenを再発行する。"""
    verify_origin(request, ctx)
    token = issue_csrf_token(ctx.settings.auth_secret(), auth.marketer_id)
    response = ok({"csrf_token": token})
    response.headers["Cache-Control"] = "no-store"
    response.headers.append("set-cookie", csrf_cookie(ctx.settings, token))
    return response
