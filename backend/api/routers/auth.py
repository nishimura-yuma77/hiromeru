"""認証API（API_DESIGN 2.9、11.1）。"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.cookies import csrf_cookie, deletion_cookies, session_cookie
from api.deps import Authenticated, Context, verify_origin
from api.request_body import read_json_body
from api.responses import ok
from core.security import issue_csrf_token, issue_session_token
from domain.requests import LoginRequest
from services.auth_service import AuthService, LoginPortal
from services.context import ServiceContext
from services.validation import parse_json_object, validate_model

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin"])


async def _login(request: Request, ctx: ServiceContext, portal: LoginPortal) -> JSONResponse:
    """認証し、共通の認証Cookieと `csrf_token` Cookieを発行する。失敗時はCookieを発行しない。"""
    body = validate_model(LoginRequest, parse_json_object(await read_json_body(request)))
    user = await AuthService(ctx).login(body.email, body.password, portal=portal)
    now = ctx.clock.now()
    session_token, idle_expires_at = issue_session_token(
        ctx.settings.auth_secret(), user.user_id, user.auth_generation, now, now
    )
    csrf_token = issue_csrf_token(ctx.settings.auth_secret(), user.user_id)
    data: dict[str, object] = {"user_id": user.user_id, "email": user.email}
    if portal == "admin":
        data["is_admin"] = True
    data["csrf_token"] = csrf_token
    response = ok(data)
    response.headers.append(
        "set-cookie", session_cookie(ctx.settings, session_token, idle_expires_at, now)
    )
    response.headers.append("set-cookie", csrf_cookie(ctx.settings, csrf_token))
    return response


@router.post("/login", dependencies=[Depends(verify_origin)])
async def login(request: Request, ctx: Context) -> JSONResponse:
    """マーケターユーザーのログイン。管理ユーザーは管理用の入口を使う。

    ログインは `csrf_token` Cookieをまだ持たないため、Origin検証だけを適用する。
    """
    return await _login(request, ctx, "marketer")


@admin_router.post("/login", dependencies=[Depends(verify_origin)])
async def admin_login(request: Request, ctx: Context) -> JSONResponse:
    """管理ユーザーのログイン。マーケターユーザーは同じ認証失敗として拒否する。"""
    return await _login(request, ctx, "admin")


@router.post("/logout", dependencies=[Depends(verify_origin)])
async def logout(ctx: Context) -> JSONResponse:
    """認証Cookieと `csrf_token` Cookieを削除する。未ログインでも同じ結果を返す。"""
    response = ok(None)
    for value in deletion_cookies(ctx.settings):
        response.headers.append("set-cookie", value)
    return response


@router.get("/me")
async def me(auth: Authenticated) -> JSONResponse:
    """ログイン中のユーザーの情報を返す。`csrf_token` と `company_id` は返さない。"""
    return ok({"user_id": auth.user_id, "email": auth.email, "is_admin": auth.is_admin})


@router.post("/csrf")
async def reissue_csrf(request: Request, ctx: Context, auth: Authenticated) -> JSONResponse:
    """認証とOriginを検証し、現在のユーザー用CSRF Tokenを再発行する。"""
    verify_origin(request, ctx)
    token = issue_csrf_token(ctx.settings.auth_secret(), auth.user_id)
    response = ok({"csrf_token": token})
    response.headers["Cache-Control"] = "no-store"
    response.headers.append("set-cookie", csrf_cookie(ctx.settings, token))
    return response
