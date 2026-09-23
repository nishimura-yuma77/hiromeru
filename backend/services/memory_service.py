"""長期記憶の参照と忘却（API_DESIGN 6.7、7.1）。"""

from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from core.errors import AppError
from core.logging import get_logger, safe_error_text
from domain.cursor import CursorValue, encode_cursor
from domain.timefmt import format_utc
from repositories.campaigns import CampaignRepository
from repositories.memories import MemoryRepository
from services.context import AuthContext, ServiceContext
from services.paging import normalize_query, read_cursor, require_datetime, require_int
from services.views import (
    MemoryCampaignListView,
    MemoryListView,
    MemoryPostListView,
    MemoryView,
)

# 記憶の内容は機密を含み得るため、ログには出さない（API_DESIGN 7.1）。
_log = get_logger(__name__)
_CURSOR_KIND = "memories"
_CAMPAIGNS_CURSOR_KIND = "memory_campaigns"
_POSTS_CURSOR_KIND = "memory_posts"
_CARD_RELATION_LIMIT = 3


class MemoryService:
    """記憶の一覧と削除。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def list(
        self,
        auth: AuthContext,
        *,
        query: str | None,
        campaign_id: int | None,
        limit: int,
        cursor: str | None,
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
            values = read_cursor(cursor, _CURSOR_KIND)
            after_id = require_int(values, "id")
            if "campaign_id" not in values or values["campaign_id"] != campaign_id:
                raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
        vector = await self._ctx.embedding.embed(search) if search is not None else None
        async with self._ctx.session_factory() as session:
            repository = MemoryRepository(session)
            if (
                campaign_id is not None
                and await CampaignRepository(session).get(auth.company_id, campaign_id) is None
            ):
                raise AppError("CAMPAIGN_NOT_FOUND")
            next_cursor: str | None = None
            if vector is not None:
                rows = await repository.search(auth.company_id, vector, campaign_id, limit)
            else:
                fetched = await repository.list_recent(
                    auth.company_id,
                    campaign_id=campaign_id,
                    limit=limit + 1,
                    after_id=after_id,
                )
                rows = fetched[:limit]
                if len(fetched) > limit:
                    next_cursor = encode_cursor(
                        _CURSOR_KIND, {"id": rows[-1].id, "campaign_id": campaign_id}
                    )
            relations = await repository.relations(auth.company_id, [row.id for row in rows])
        memories = []
        for row in rows:
            campaigns = relations.campaigns.get(row.id, [])
            posts = relations.posts.get(row.id, [])
            memories.append(
                MemoryView(
                    row.id,
                    row.content,
                    row.similarity,
                    campaigns[:_CARD_RELATION_LIMIT],
                    self._campaign_cursor(row.id, campaigns[_CARD_RELATION_LIMIT - 1])
                    if len(campaigns) > _CARD_RELATION_LIMIT
                    else None,
                    posts[:_CARD_RELATION_LIMIT],
                    self._post_cursor(row.id, posts[_CARD_RELATION_LIMIT - 1])
                    if len(posts) > _CARD_RELATION_LIMIT
                    else None,
                )
            )
        return MemoryListView(memories, next_cursor)

    async def campaigns(
        self, auth: AuthContext, memory_id: int, *, limit: int, cursor: str | None
    ) -> MemoryCampaignListView:
        """記憶に関連する施策を施策IDの降順で返す。"""
        after_id = None
        if cursor is not None:
            values = self._relation_cursor(cursor, _CAMPAIGNS_CURSOR_KIND, memory_id)
            after_id = require_int(values, "campaign_id")
        async with self._ctx.session_factory() as session:
            repository = MemoryRepository(session)
            if not await repository.exists(auth.company_id, memory_id):
                raise AppError("MEMORY_NOT_FOUND")
            fetched = await repository.related_campaigns(
                auth.company_id, memory_id, limit=limit + 1, after_id=after_id
            )
        shown = fetched[:limit]
        next_cursor = self._campaign_cursor(memory_id, shown[-1]) if len(fetched) > limit else None
        return MemoryCampaignListView(shown, next_cursor)

    async def posts(
        self, auth: AuthContext, memory_id: int, *, limit: int, cursor: str | None
    ) -> MemoryPostListView:
        """記憶に関連する公開成功済み投稿を公開日時・IDの降順で返す。"""
        after = None
        if cursor is not None:
            values = self._relation_cursor(cursor, _POSTS_CURSOR_KIND, memory_id)
            after = (require_datetime(values, "published_at"), require_int(values, "post_id"))
        async with self._ctx.session_factory() as session:
            repository = MemoryRepository(session)
            if not await repository.exists(auth.company_id, memory_id):
                raise AppError("MEMORY_NOT_FOUND")
            fetched = await repository.related_posts(
                auth.company_id, memory_id, limit=limit + 1, after=after
            )
        shown = fetched[:limit]
        next_cursor = self._post_cursor(memory_id, shown[-1]) if len(fetched) > limit else None
        return MemoryPostListView(shown, next_cursor)

    @staticmethod
    def _relation_cursor(cursor: str, kind: str, memory_id: int) -> dict[str, CursorValue]:
        values = read_cursor(cursor, kind)
        if values.get("memory_id") != memory_id:
            raise AppError("INVALID_ARGUMENT", "cursor が正しくありません。")
        return values

    @staticmethod
    def _campaign_cursor(memory_id: int, campaign: tuple[int, str, datetime | None]) -> str:
        return encode_cursor(
            _CAMPAIGNS_CURSOR_KIND,
            {"memory_id": memory_id, "campaign_id": campaign[0]},
        )

    @staticmethod
    def _post_cursor(memory_id: int, post: tuple[int, datetime]) -> str:
        return encode_cursor(
            _POSTS_CURSOR_KIND,
            {
                "memory_id": memory_id,
                "post_id": post[0],
                "published_at": format_utc(post[1]),
            },
        )

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
