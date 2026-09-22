"""記憶API（API_DESIGN 6.7、7.1）。"""

from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from api.deps import Authenticated, Context, CsrfProtected
from api.responses import ok
from api.serializers import serialize_memory_list
from domain.constants import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT
from services.memory_service import MemoryService

router = APIRouter(prefix="/api/v1/memories", tags=["memories"])


@router.get("")
async def list_memories(
    ctx: Context,
    auth: Authenticated,
    query: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> JSONResponse:
    """長期記憶を、関連する施策と投稿とあわせて返す。"""
    view = await MemoryService(ctx).list(auth, query=query, limit=limit, cursor=cursor)
    return ok(serialize_memory_list(view))


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: Annotated[int, Path(gt=0)], ctx: Context, auth: CsrfProtected
) -> JSONResponse:
    """長期記憶の内容とEmbeddingを削除する。Agent履歴・冪等性は使わない。"""
    await MemoryService(ctx).delete(auth, memory_id)
    return ok({"memory_id": memory_id, "deleted": True})
