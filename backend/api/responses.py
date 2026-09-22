"""共通のResponse形式（API_DESIGN 2.5、2.6）。"""

from typing import Any

from fastapi.responses import JSONResponse

from core.errors import AppError


def ok(data: Any, status_code: int = 200) -> JSONResponse:  # noqa: ANN401 - JSON化済みの値
    """成功Response。"""
    return JSONResponse({"success": True, "data": data, "error": None}, status_code=status_code)


def error_response(error: AppError) -> JSONResponse:
    """エラーResponse。`Retry-After` が指定されていれば付与する。"""
    headers = (
        {"Retry-After": str(error.retry_after_seconds)}
        if error.retry_after_seconds is not None
        else None
    )
    return JSONResponse(
        {
            "success": False,
            "data": None,
            "error": error.serialize(),
        },
        status_code=error.status_code,
        headers=headers,
    )
