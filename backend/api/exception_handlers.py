"""例外をHTTP Responseへ変換する処理を1か所に集約する（BE_STD 7章）。"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.container import get_service_context
from api.cookies import deletion_cookies
from api.responses import error_response
from clients.errors import EmbeddingError
from core.errors import AppError
from core.logging import get_logger, safe_error_text
from services.validation import validation_field_errors

_log = get_logger(__name__)


def _respond(request: Request, error: AppError) -> JSONResponse:
    response = error_response(error)
    if error.code == "UNAUTHENTICATED":
        # 署名不正・期限切れ・行なしのCookieを削除する（API_DESIGN 2.8）。
        for value in deletion_cookies(get_service_context(request).settings):
            response.headers.append("set-cookie", value)
    return response


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101
    if exc.status_code >= 500:
        _log.error("app_error", code=exc.code, agent_turn_id=exc.agent_turn_id)
    return _respond(request, exc)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    """Path・Queryの検証エラー。入力値は返さない。"""
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    return _respond(
        request,
        AppError("INVALID_ARGUMENT", field_errors=validation_field_errors(exc.errors())),
    )


async def _handle_embedding_error(request: Request, exc: Exception) -> JSONResponse:
    """参照APIの意味検索で、Embeddingを生成できなかった。"""
    _log.warning("embedding_failed", error=safe_error_text(exc))
    return _respond(request, AppError("EMBEDDING_FAILED"))


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """想定外の例外。内部情報を返さず、マスクした内容を1回だけログへ出す。"""
    _log.error("unexpected_error", error=safe_error_text(exc))
    return _respond(request, AppError("INTERNAL_ERROR"))


def register_exception_handlers(app: FastAPI) -> None:
    """例外ハンドラを登録する。"""
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(EmbeddingError, _handle_embedding_error)
    app.add_exception_handler(Exception, _handle_unexpected)
