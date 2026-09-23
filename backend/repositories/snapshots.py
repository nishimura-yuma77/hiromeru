"""短期一覧Snapshotの共通Repository。"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from domain.constants import LIST_SNAPSHOT_TTL_SECONDS
from models import ApiListSnapshot, ApiListSnapshotItem


@dataclass(frozen=True)
class SnapshotPage:
    """検証済みSnapshotのメタデータと固定Projection Slice。"""

    summary: dict[str, Any] | None
    items: list[dict[str, Any]]


class SnapshotRepository:
    """投稿・指標一覧で共有するSnapshotのDB操作。"""

    def __init__(self, session: AsyncSession) -> None:
        """セッションを受け取る。"""
        self._session = session

    async def cleanup_expired(self, now: datetime, limit: int) -> int:
        """期限切れSnapshotを古い順に最大`limit`件削除する。"""
        expired_ids = (
            select(ApiListSnapshot.id)
            .where(ApiListSnapshot.expires_at <= now)
            .order_by(ApiListSnapshot.expires_at, ApiListSnapshot.id)
            .limit(limit)
        )
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                delete(ApiListSnapshot)
                .where(ApiListSnapshot.id.in_(expired_ids))
                .execution_options(synchronize_session=False)
            ),
        )
        return result.rowcount

    async def create(
        self,
        *,
        snapshot_id: uuid.UUID,
        marketer_id: int,
        resource: str,
        filter_hash: str,
        items: list[dict[str, Any]],
        now: datetime,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Snapshotメタデータと全固定Projectionを保存する。"""
        self._session.add(
            ApiListSnapshot(
                id=snapshot_id,
                marketer_id=marketer_id,
                resource=resource,
                filter_hash=filter_hash,
                summary=summary,
                created_at=now,
                expires_at=now + timedelta(seconds=LIST_SNAPSHOT_TTL_SECONDS),
            )
        )
        self._session.add_all(
            ApiListSnapshotItem(snapshot_id=snapshot_id, position=position, item=item)
            for position, item in enumerate(items)
        )
        await self._session.flush()

    async def read_page(
        self,
        *,
        snapshot_id: uuid.UUID,
        marketer_id: int,
        resource: str,
        filter_hash: str,
        now: datetime,
        position: int,
        limit: int,
    ) -> SnapshotPage | None:
        """所有者・種別・条件・期限が一致するSnapshotから固定Projectionだけを読む。"""
        snapshot = await self._session.scalar(
            select(ApiListSnapshot).where(
                ApiListSnapshot.id == snapshot_id,
                ApiListSnapshot.marketer_id == marketer_id,
                ApiListSnapshot.resource == resource,
                ApiListSnapshot.filter_hash == filter_hash,
                ApiListSnapshot.expires_at > now,
            )
        )
        if snapshot is None:
            return None
        rows = list(
            await self._session.execute(
                select(ApiListSnapshotItem.position, ApiListSnapshotItem.item)
                .where(
                    ApiListSnapshotItem.snapshot_id == snapshot_id,
                    ApiListSnapshotItem.position >= position,
                )
                .order_by(ApiListSnapshotItem.position)
                .limit(limit + 1)
            )
        )
        if not rows or rows[0][0] != position:
            return None
        return SnapshotPage(snapshot.summary, [row[1] for row in rows])
