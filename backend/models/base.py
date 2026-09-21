"""SQLAlchemyの宣言的基底クラスと、モデル共通の部品。"""

from datetime import datetime
from enum import Enum
from typing import Any, ClassVar

from sqlalchemy import DateTime, Index, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全モデルの基底クラス。

    関連（relationship）は定義しない。取得は Repository が明示的な JOIN で行い、
    遅延読み込み（lazy load）に頼らない（BE_STD 11章）。
    """

    type_annotation_map: ClassVar[dict[type, Any]] = {datetime: DateTime(timezone=True)}


def pg_enum(enum_class: type[Enum], name: str) -> ENUM:
    """既存のPostgreSQL enum型を参照する列型を返す。

    型の作成はマイグレーションで行うため、`create_type=False` とする。
    """
    return ENUM(
        enum_class,
        name=name,
        create_type=False,
        values_callable=lambda members: [member.value for member in members],
    )


def created_at_column() -> Mapped[datetime]:
    """作成日時の列（DB既定値 now()）を返す。"""
    return mapped_column(server_default=func.now())


def updated_at_column() -> Mapped[datetime]:
    """更新日時の列（DB既定値 now()）を返す。"""
    return mapped_column(server_default=func.now())


def hnsw_cosine_index(name: str, column: str) -> Index:
    """コサイン距離のHNSW索引を返す（DB.dbml: vector_cosine_ops）。"""
    return Index(
        name,
        column,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={column: "vector_cosine_ops"},
    )
