"""施策の参照と、Sessionに関わらない直接編集（API_DESIGN 4.2、6.2、6.3）。"""

from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from clients.errors import EmbeddingError
from core.errors import AppError
from core.logging import get_logger, safe_error_text
from domain.campaign_rules import CampaignContent, campaign_field_errors
from domain.constants import CAMPAIGN_DETAIL_MEMORIES_LIMIT, CAMPAIGN_DETAIL_POSTS_LIMIT
from domain.cursor import encode_cursor
from domain.metrics import EMPTY_SUMMARY
from domain.requests import CampaignEditRequest
from domain.search_text import build_campaign_search_text, content_hash
from domain.timefmt import format_utc
from models import Campaign
from repositories.campaigns import CampaignRepository
from repositories.memories import MemoryRepository
from repositories.posts import PostRepository
from services.context import AuthContext, ServiceContext
from services.metrics_view import to_metrics_view
from services.paging import (
    normalize_query,
    read_cursor,
    require_datetime,
    require_int,
    validate_range,
)
from services.views import (
    CampaignDetailView,
    CampaignEditView,
    CampaignListItemView,
    CampaignListView,
    CampaignPostView,
    CampaignView,
    MemoryBriefView,
)

_log = get_logger(__name__)
_CURSOR_KIND = "campaigns"


def _to_view(campaign: Campaign) -> CampaignView:
    return CampaignView(
        campaign.id,
        campaign.title,
        campaign.target_profile,
        campaign.background,
        campaign.objective,
        campaign.plan,
        campaign.created_at,
        campaign.updated_at,
        campaign.archived_at,
    )


class CampaignService:
    """施策の一覧・詳細・直接編集。"""

    def __init__(self, ctx: ServiceContext) -> None:
        """サービスの依存を受け取る。"""
        self._ctx = ctx

    async def list(
        self,
        auth: AuthContext,
        *,
        query: str | None,
        archived: bool | None,
        created_from: datetime | None,
        created_to: datetime | None,
        limit: int,
        cursor: str | None,
    ) -> CampaignListView:
        """施策を新しい順、または意味検索で返す（6.2）。

        Raises:
            AppError: query と cursor の同時指定、不正な条件（INVALID_ARGUMENT）。
        """
        search = normalize_query(query)
        if search is not None and cursor is not None:
            raise AppError("INVALID_ARGUMENT", "query と cursor は同時に指定できません。")
        validate_range(created_from, created_to, "created_from・created_to")
        after = None
        if cursor is not None:
            values = read_cursor(cursor, _CURSOR_KIND)
            after = (require_datetime(values, "created_at"), require_int(values, "id"))
        # Embedding APIはDBのTransactionの外で呼び出す（BE_STD 12章）。
        vector = await self._ctx.embedding.embed(search) if search is not None else None
        async with self._ctx.session_factory() as session:
            repository = CampaignRepository(session)
            similarities: dict[int, float | None] = {}
            next_cursor: str | None = None
            if vector is not None:
                found = await repository.search(
                    auth.company_id,
                    vector,
                    created_from=created_from,
                    created_to=created_to,
                    archived=archived,
                    limit=limit,
                )
                campaigns = [campaign for campaign, _ in found]
                similarities = {campaign.id: score for campaign, score in found}
            else:
                rows = await repository.list_by_created(
                    auth.company_id,
                    created_from=created_from,
                    created_to=created_to,
                    archived=archived,
                    limit=limit + 1,
                    after=after,
                )
                campaigns = rows[:limit]
                if len(rows) > limit:
                    last = campaigns[-1]
                    next_cursor = encode_cursor(
                        _CURSOR_KIND, {"created_at": format_utc(last.created_at), "id": last.id}
                    )
            summaries = await PostRepository(session).summarize(
                auth.company_id, campaign_ids=[campaign.id for campaign in campaigns]
            )
        items = [
            CampaignListItemView(
                campaign.id,
                campaign.title,
                campaign.objective,
                campaign.created_at,
                campaign.updated_at,
                campaign.archived_at,
                similarities.get(campaign.id),
                summaries.get(campaign.id, EMPTY_SUMMARY),
            )
            for campaign in campaigns
        ]
        return CampaignListView(items, next_cursor)

    async def detail(self, auth: AuthContext, campaign_id: int) -> CampaignDetailView:
        """施策の全項目と、紐づく投稿・記憶、計測の集計を返す（6.3）。

        Raises:
            AppError: 施策が存在しない、または別会社に属する場合（CAMPAIGN_NOT_FOUND）。
        """
        async with self._ctx.session_factory() as session:
            campaign = await CampaignRepository(session).get(auth.company_id, campaign_id)
            if campaign is None:
                raise AppError("CAMPAIGN_NOT_FOUND")
            posts = PostRepository(session)
            summary = (await posts.summarize(auth.company_id, campaign_ids=[campaign_id])).get(
                campaign_id, EMPTY_SUMMARY
            )
            post_rows = await posts.list_for_campaign(
                auth.company_id, campaign_id, CAMPAIGN_DETAIL_POSTS_LIMIT + 1
            )
            memory_rows = await MemoryRepository(session).list_for_campaign(
                auth.company_id, campaign_id, CAMPAIGN_DETAIL_MEMORIES_LIMIT + 1
            )
        shown_posts = post_rows[:CAMPAIGN_DETAIL_POSTS_LIMIT]
        shown_memories = memory_rows[:CAMPAIGN_DETAIL_MEMORIES_LIMIT]
        return CampaignDetailView(
            campaign=_to_view(campaign),
            metrics_summary=summary,
            posts=[
                CampaignPostView(
                    row.post.id, row.post.body, row.post.published_at, to_metrics_view(row.metric)
                )
                for row in shown_posts
            ],
            has_more_posts=len(post_rows) > CAMPAIGN_DETAIL_POSTS_LIMIT,
            memories=[MemoryBriefView(row.id, row.content) for row in shown_memories],
            has_more_memories=len(memory_rows) > CAMPAIGN_DETAIL_MEMORIES_LIMIT,
        )

    async def edit(
        self, auth: AuthContext, campaign_id: int, request: CampaignEditRequest
    ) -> CampaignEditView:
        """保存済みの施策を、フォームの内容で全項目上書きする（4.2）。

        Agent履歴・冪等性レコードは作らない。記録は構造化ログ（本文なし）だけに残す。

        Raises:
            AppError: 施策なし、業務条件違反、競合、Embedding・DB保存の失敗。
        """
        try:
            view = await self._edit(auth, campaign_id, request)
        except AppError as error:
            _log.info("campaign_edit", **self._log_fields(auth, campaign_id), result=error.code)
            raise
        _log.info("campaign_edit", **self._log_fields(auth, campaign_id), result="succeeded")
        return view

    @staticmethod
    def _log_fields(auth: AuthContext, campaign_id: int) -> dict[str, int]:
        return {
            "company_id": auth.company_id,
            "marketer_id": auth.marketer_id,
            "campaign_id": campaign_id,
        }

    async def _edit(
        self, auth: AuthContext, campaign_id: int, request: CampaignEditRequest
    ) -> CampaignEditView:
        content = CampaignContent(
            request.title,
            request.target_profile,
            request.background,
            request.objective,
            request.plan,
        )
        async with self._ctx.session_factory() as session:
            repository = CampaignRepository(session)
            existing = await repository.get(auth.company_id, campaign_id)
            if existing is None:
                raise AppError("CAMPAIGN_NOT_FOUND")
            if existing.archived_at is not None:
                raise AppError("CAMPAIGN_ARCHIVED")
            field_errors = campaign_field_errors(content)
            if field_errors:
                raise AppError("INVALID_CAMPAIGN", field_errors=field_errors)
            # Embedding生成の前に競合を検出する。timestamptz の値として比較する。
            if existing.updated_at != request.expected_updated_at:
                raise AppError("CAMPAIGN_CONFLICT")
            stored_hash = await repository.get_embedding_hash(campaign_id)
        search_text = build_campaign_search_text(content)
        digest = content_hash(search_text)
        embedding = None
        if stored_hash != digest:
            try:
                embedding = await self._ctx.embedding.embed(search_text)
            except EmbeddingError as error:
                _log.warning("campaign_embedding_failed", error=safe_error_text(error))
                raise AppError("EMBEDDING_FAILED") from None
        now = self._ctx.clock.now()
        try:
            async with self._ctx.session_factory() as session, session.begin():
                repository = CampaignRepository(session)
                updated = await repository.update_if_unchanged(
                    auth.company_id, campaign_id, request.expected_updated_at, content, now
                )
                if not updated:
                    raise AppError("CAMPAIGN_CONFLICT")
                if embedding is not None:
                    await repository.upsert_embedding(campaign_id, embedding, digest, now)
        except SQLAlchemyError as error:
            _log.error("campaign_edit_save_failed", error=safe_error_text(error))
            raise AppError("CAMPAIGN_UPDATE_FAILED") from None
        return CampaignEditView(campaign_id, content.title, now)
