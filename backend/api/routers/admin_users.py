"""自社ユーザー管理API（API_DESIGN 11.2）と、招待からのパスワード設定API（同11.3）。

管理APIは認証済み管理ユーザーだけが呼び出せる。対象の会社は本人の所属から決め、
`company_id` をRequestから受け取らない。Agent履歴には保存しない。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse

from api.deps import AdminReader, AdminWriter, Context, verify_origin
from api.request_body import read_json_body
from api.responses import ok
from domain.requests import AcceptInvitationRequest, InviteUserRequest, UpdateUserRequest
from repositories.users import CompanyUserView
from services.user_admin_service import CompanyUserPage, UserAdminService
from services.validation import parse_json_object, validate_model

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])
invitation_router = APIRouter(prefix="/api/v1/invitation-acceptances", tags=["invitations"])

UserId = Annotated[int, Path(gt=0)]


def serialize_company_user(view: CompanyUserView) -> dict[str, object]:
    """自社ユーザーの返却形式。パスワードハッシュ・招待トークン・会社IDは返さない。"""
    return {
        "user_id": view.user_id,
        "name": view.name,
        "email": view.email,
        "user_type": view.user_type,
        "status": view.status.value,
        "is_responsible": view.is_responsible,
        "email_status": None if view.email_status is None else view.email_status.value,
    }


def _serialize_page(page: CompanyUserPage) -> dict[str, object]:
    return {
        "users": [serialize_company_user(user) for user in page.users],
        "page": page.page,
        "page_size": page.page_size,
        "total_count": page.total_count,
        "total_pages": page.total_pages,
    }


@router.get("")
async def list_users(
    ctx: Context, auth: AdminReader, page: Annotated[int, Query(ge=1)] = 1
) -> JSONResponse:
    """自社ユーザーを登録日時の新しい順に20件ずつ返す。"""
    return ok(_serialize_page(await UserAdminService(ctx).list(auth, page)))


@router.post("")
async def invite_user(request: Request, ctx: Context, auth: AdminWriter) -> JSONResponse:
    """招待中ユーザーと招待リンクを保存してから招待メールを送る。"""
    body = validate_model(InviteUserRequest, parse_json_object(await read_json_body(request)))
    user = await UserAdminService(ctx).invite(
        auth, user_type=body.user_type, name=body.name, email=body.email
    )
    return ok(
        {
            "user_id": user.user_id,
            "status": user.status.value,
            "email_status": None if user.email_status is None else user.email_status.value,
        },
        status_code=201,
    )


@router.patch("/{user_id}")
async def update_user(
    user_id: UserId, request: Request, ctx: Context, auth: AdminWriter
) -> JSONResponse:
    """表示名とユーザー種別を部分更新する。"""
    body = validate_model(UpdateUserRequest, parse_json_object(await read_json_body(request)))
    user = await UserAdminService(ctx).update(
        auth, user_id, name=body.name, user_type=body.user_type
    )
    return ok({"user": serialize_company_user(user)})


@router.post("/{user_id}/suspensions")
async def suspend_user(user_id: UserId, ctx: Context, auth: AdminWriter) -> JSONResponse:
    """ユーザーを利用停止する。"""
    user = await UserAdminService(ctx).suspend(auth, user_id)
    return ok({"user": serialize_company_user(user)})


@router.post("/{user_id}/reactivations")
async def reactivate_user(user_id: UserId, ctx: Context, auth: AdminWriter) -> JSONResponse:
    """停止中のユーザーを招待中へ戻し、新しい招待メールを送る。"""
    user = await UserAdminService(ctx).reactivate(auth, user_id)
    return ok({"user": serialize_company_user(user)})


@router.post("/{user_id}/invitations")
async def resend_invitation(user_id: UserId, ctx: Context, auth: AdminWriter) -> JSONResponse:
    """招待中のユーザーへ、新しいリンクで招待メールを再送する。"""
    status = await UserAdminService(ctx).resend(auth, user_id)
    return ok({"email_status": status.value}, status_code=201)


@invitation_router.post("", dependencies=[Depends(verify_origin)])
async def accept_invitation(request: Request, ctx: Context) -> JSONResponse:
    """未ログインで招待トークンを検証し、パスワードを設定する。認証Cookieは発行しない。

    トークンはBodyで受け取り、URL・ログ・Responseに含めない。
    """
    body = validate_model(AcceptInvitationRequest, parse_json_object(await read_json_body(request)))
    user_type = await UserAdminService(ctx).accept(body.token, body.password)
    response = ok({"user_type": user_type})
    response.headers["Cache-Control"] = "no-store"
    return response
