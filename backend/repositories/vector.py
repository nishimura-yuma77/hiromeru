"""pgvector の距離演算の型付きラッパー。"""

from sqlalchemy import ColumnElement, Float
from sqlalchemy.orm import InstrumentedAttribute


def cosine_distance(
    column: InstrumentedAttribute[list[float]], vector: list[float]
) -> ColumnElement[float]:
    """コサイン距離（0に近いほど類似）を返す式。類似度は `1 - 距離`。"""
    expression: ColumnElement[float] = column.cosine_distance(vector)  # pyright: ignore[reportAttributeAccessIssue]
    return expression.cast(Float)
