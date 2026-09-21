"""長期記憶の参照と忘却（API_DESIGN 6.7、7.1）。"""

from sqlalchemy.exc import SQLAlchemyError

from core.errors import AppError
from core.logging import get_logger, safe_error_text
from domain.cursor import encode_cursor
from repositories.memories import MemoryRepository
from services.context import AuthContext, ServiceContext
from services.paging import normalize_query, read_cursor, require_int
from services.views import MemoryListView, MemoryView

# 記憶の内容は機密を含み得るため、ログには出さない（API_DESIGN 7.1）。
_log = get_logger(__name__)
_CURSOR_KIND = "memories"


class MemoryService:
    """記憶の一覧と削除。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def list(
        self, auth: AuthContext, *, query: str | None, limit: int, cursor: str | None
    ) -> MemoryListView:
        """記憶を新しい順（id の降順）、または意味検索で返す（6.7）。

        Raises:
            AppError: query と cursor の同時指定、不正な条件（INVALID_ARGUMENT）。
        """
        search = normalize_query(query)
        if search is not None and cursor is not None:
            raise AppError("INVALID_ARGUMENT", "query と cursor は同時に指定できません。")
        after_id = None
        if cursor is not None:
            after_id = require_int(read_cursor(cursor, _CURSOR_KIND), "id")
        vector = await self._ctx.embedding.embed(search) if search is not None else None
        async with self._ctx.session_factory() as session:
            repository = MemoryRepository(session)
            next_cursor: str | None = None
            if vector is not None:
                rows = await repository.search(auth.company_id, vector, limit)
            else:
                fetched = await repository.list_recent(
                    auth.company_id, limit=limit + 1, after_id=after_id
                )
                rows = fetched[:limit]
                if len(fetched) > limit:
                    next_cursor = encode_cursor(_CURSOR_KIND, {"id": rows[-1].id})
            relations = await repository.relations(auth.company_id, [row.id for row in rows])
        memories = [
            MemoryView(
                row.id,
                row.content,
                row.similarity,
                relations.campaigns.get(row.id, []),
                relations.posts.get(row.id, []),
            )
            for row in rows
        ]
        return MemoryListView(memories, next_cursor)

    async def delete(self, auth: AuthContext, memory_id: int) -> None:
        """記憶（内容とEmbedding）を削除する。関連行は cascade で同時に削除される。

        Agent履歴へは保存しない。記録は構造化ログ（内容なし）だけに残す。

        Raises:
            AppError: 存在しない、または別会社（MEMORY_NOT_FOUND）。DB失敗（MEMORY_DELETE_FAILED）。
        """
        fields = {
            "company_id": auth.company_id,
            "marketer_id": auth.marketer_id,
            "memory_id": memory_id,
        }
        try:
            async with self._ctx.session_factory() as session, session.begin():
                deleted = await MemoryRepository(session).delete(auth.company_id, memory_id)
        except SQLAlchemyError as error:
            _log.error("memory_delete", **fields, result="failed", error=safe_error_text(error))
            raise AppError("MEMORY_DELETE_FAILED") from None
        if not deleted:
            _log.info("memory_delete", **fields, result="MEMORY_NOT_FOUND")
            raise AppError("MEMORY_NOT_FOUND")
        _log.info("memory_delete", **fields, result="succeeded")
