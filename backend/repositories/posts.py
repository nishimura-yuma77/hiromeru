"""公開済み投稿・トラッキング・計測のRepository。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from domain.constants import METRICS_DELAY_DAYS
from domain.enums import ApiIdempotencyStatus, ApiOperation, PostMetricStatus
from domain.metrics import MetricsSummary
from models import (
    ApiIdempotencyRequest,
    Campaign,
    Post,
    PostEmbedding,
    PostMetric,
    PostTrackingLink,
)
from repositories.vector import cosine_distance


@dataclass(frozen=True)
class PostRow:
    """投稿一覧・詳細の1行。"""

    post: Post
    campaign_title: str
    campaign_archived_at: datetime | None
    metric: PostMetric
    similarity: float | None = None


@dataclass(frozen=True)
class NewPost:
    """X公開成功後に保存する投稿の内容。"""

    company_id: int
    marketer_id: int
    campaign_id: int
    api_idempotency_request_id: int
    body: str
    x_post_id: str
    published_at: datetime
    landing_url: str
    utm_source: str
    utm_medium: str
    utm_campaign: str
    utm_content: str
    tracked_url: str
    embedding: list[float]
    content_hash: str


@dataclass(frozen=True)
class PostFilter:
    """投稿の絞り込み条件。"""

    campaign_id: int | None = None
    published_from: datetime | None = None
    published_to: datetime | None = None


@dataclass(frozen=True)
class PostPage:
    """投稿一覧の並び順とカーソル。"""

    sort: Literal["published_at", "x_pv_count"]
    order: Literal["asc", "desc"]
    cursor: dict[str, Any] | None = None


def _published_stmt(company_id: int) -> Select[Any]:
    """公開済み投稿だけを対象とする基本のSELECT（API_DESIGN 3章「公開済みPostの取得境界」）。"""
    return (
        select(Post, Campaign.title, Campaign.archived_at, PostMetric)
        .join(ApiIdempotencyRequest, ApiIdempotencyRequest.id == Post.api_idempotency_request_id)
        .join(Campaign, Campaign.id == Post.campaign_id)
        .join(PostMetric, PostMetric.post_id == Post.id)
        .where(
            Post.company_id == company_id,
            ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
            ApiIdempotencyRequest.status == ApiIdempotencyStatus.SUCCEEDED,
        )
    )


def _apply_filter(stmt: Select[Any], flt: PostFilter) -> Select[Any]:
    if flt.campaign_id is not None:
        stmt = stmt.where(Post.campaign_id == flt.campaign_id)
    if flt.published_from is not None:
        stmt = stmt.where(Post.published_at >= flt.published_from)
    if flt.published_to is not None:
        stmt = stmt.where(Post.published_at < flt.published_to)
    return stmt


class PostRepository:
    """投稿のDBアクセス。すべて会社の条件を含める。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def insert_published(self, new: NewPost) -> Post:
        """投稿・Embedding・トラッキングURL・計測予定を保存する。"""
        post = Post(
            company_id=new.company_id,
            created_by_marketer_id=new.marketer_id,
            campaign_id=new.campaign_id,
            api_idempotency_request_id=new.api_idempotency_request_id,
            body=new.body,
            x_post_id=new.x_post_id,
            published_at=new.published_at,
            created_at=new.published_at,
            updated_at=new.published_at,
        )
        self._session.add(post)
        await self._session.flush()
        self._session.add_all(
            [
                PostEmbedding(
                    post_id=post.id,
                    embedding=new.embedding,
                    content_hash=new.content_hash,
                    created_at=new.published_at,
                ),
                PostTrackingLink(
                    post_id=post.id,
                    landing_url=new.landing_url,
                    utm_source=new.utm_source,
                    utm_medium=new.utm_medium,
                    utm_campaign=new.utm_campaign,
                    utm_content=new.utm_content,
                    tracked_url=new.tracked_url,
                    created_at=new.published_at,
                    updated_at=new.published_at,
                ),
                PostMetric(
                    post_id=post.id,
                    scheduled_at=new.published_at + timedelta(days=METRICS_DELAY_DAYS),
                    status=PostMetricStatus.PENDING,
                ),
            ]
        )
        await self._session.flush()
        return post

    async def get_published(self, company_id: int, post_id: int) -> PostRow | None:
        """公開済み投稿を1件取得する。未公開・別会社は None。"""
        stmt = _published_stmt(company_id).where(Post.id == post_id)
        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else PostRow(row[0], row[1], row[2], row[3])

    async def get_tracking(self, post_id: int) -> PostTrackingLink | None:
        """投稿のトラッキングURLを取得する。"""
        stmt = select(PostTrackingLink).where(PostTrackingLink.post_id == post_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def published_ids(self, company_id: int, post_ids: tuple[int, ...]) -> set[int]:
        """会社に属する公開成功済みPost IDだけを返す。"""
        if not post_ids:
            return set()
        stmt = (
            select(Post.id)
            .join(
                ApiIdempotencyRequest,
                ApiIdempotencyRequest.id == Post.api_idempotency_request_id,
            )
            .where(
                Post.company_id == company_id,
                Post.id.in_(post_ids),
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.SUCCEEDED,
            )
        )
        return set((await self._session.execute(stmt)).scalars())

    async def list_for_campaign(
        self, company_id: int, campaign_id: int, limit: int
    ) -> list[PostRow]:
        """施策の公開済み投稿を、公開日時の降順で返す。"""
        stmt = (
            _published_stmt(company_id)
            .where(Post.campaign_id == campaign_id)
            .order_by(Post.published_at.desc(), Post.id.desc())
            .limit(limit)
        )
        return [PostRow(r[0], r[1], r[2], r[3]) for r in await self._session.execute(stmt)]

    async def list_posts(
        self, company_id: int, flt: PostFilter, page: PostPage, limit: int | None = None
    ) -> list[PostRow]:
        """並び替えとカーソルに従って公開済み投稿を返す（API_DESIGN 6.4）。"""
        stmt = _apply_filter(_published_stmt(company_id), flt)
        descending = page.order == "desc"
        cursor = page.cursor
        if page.sort == "published_at":
            key = tuple_(Post.published_at, Post.id)
            if cursor is not None:
                after = tuple_(cursor["published_at"], cursor["id"])
                stmt = stmt.where(key < after if descending else key > after)
            columns = (Post.published_at, Post.id)
            stmt = stmt.order_by(*(c.desc() if descending else c.asc() for c in columns))
        else:
            stmt = self._order_by_pv(stmt, descending, cursor)
        if limit is not None:
            stmt = stmt.limit(limit)
        return [PostRow(r[0], r[1], r[2], r[3]) for r in await self._session.execute(stmt)]

    @staticmethod
    def _order_by_pv(
        stmt: Select[Any], descending: bool, cursor: dict[str, Any] | None
    ) -> Select[Any]:
        """`x_pv_count` の並び替え。値がない投稿（pending・failed）は常に末尾へ置く。"""
        pv = case(
            (PostMetric.status == PostMetricStatus.COMPLETED, PostMetric.x_pv_count),
            else_=None,
        )
        if cursor is not None:
            if not cursor["is_null"]:
                key, after = tuple_(pv, Post.id), tuple_(cursor["x_pv_count"], cursor["id"])
                stmt = stmt.where(
                    or_(
                        and_(pv.is_not(None), key < after if descending else key > after),
                        pv.is_(None),
                    )
                )
            else:
                stmt = stmt.where(
                    and_(
                        pv.is_(None),
                        tuple_(Post.published_at, Post.id)
                        < tuple_(cursor["published_at"], cursor["id"]),
                    )
                )
        has_value = pv.is_not(None)
        pv_order = pv.desc() if descending else pv.asc()
        value_id = case((has_value, Post.id))
        return stmt.order_by(
            has_value.desc(),
            pv_order.nulls_last(),
            case((pv.is_(None), Post.published_at)).desc().nulls_last(),
            (value_id.desc() if descending else value_id.asc()).nulls_last(),
            case((pv.is_(None), Post.id)).desc().nulls_last(),
        )

    async def search_posts(
        self, company_id: int, vector: list[float], flt: PostFilter, limit: int
    ) -> list[PostRow]:
        """コサイン類似度の高い順に公開済み投稿を返す。"""
        distance = cosine_distance(PostEmbedding.embedding, vector)
        stmt = _apply_filter(
            _published_stmt(company_id).join(PostEmbedding, PostEmbedding.post_id == Post.id),
            flt,
        )
        stmt = stmt.add_columns((1 - distance).label("similarity")).order_by(
            distance, Post.id.desc()
        )
        rows = await self._session.execute(stmt.limit(limit))
        return [PostRow(r[0], r[1], r[2], r[3], float(r[4])) for r in rows]

    async def summarize(
        self,
        company_id: int,
        *,
        campaign_ids: list[int] | None = None,
        published_from: datetime | None = None,
        published_to: datetime | None = None,
    ) -> dict[int, MetricsSummary]:
        """施策ごとの計測集計を返す。投稿のない施策は含まない。"""
        completed = PostMetric.status == PostMetricStatus.COMPLETED
        stmt = (
            select(
                Post.campaign_id,
                func.count(Post.id),
                func.count(Post.id).filter(completed),
                func.count(Post.id).filter(PostMetric.status == PostMetricStatus.PENDING),
                func.count(Post.id).filter(PostMetric.status == PostMetricStatus.FAILED),
                func.coalesce(func.sum(PostMetric.x_pv_count).filter(completed), 0),
                func.coalesce(func.sum(PostMetric.landing_user_count).filter(completed), 0),
            )
            .join(
                ApiIdempotencyRequest, ApiIdempotencyRequest.id == Post.api_idempotency_request_id
            )
            .join(PostMetric, PostMetric.post_id == Post.id)
            .where(
                Post.company_id == company_id,
                ApiIdempotencyRequest.operation == ApiOperation.PUBLISH_X_POST,
                ApiIdempotencyRequest.status == ApiIdempotencyStatus.SUCCEEDED,
            )
            .group_by(Post.campaign_id)
        )
        if campaign_ids is not None:
            stmt = stmt.where(Post.campaign_id.in_(campaign_ids))
        if published_from is not None:
            stmt = stmt.where(Post.published_at >= published_from)
        if published_to is not None:
            stmt = stmt.where(Post.published_at < published_to)
        return {
            row[0]: MetricsSummary(row[1], row[2], row[3], row[4], int(row[5]), int(row[6]))
            for row in await self._session.execute(stmt)
        }
