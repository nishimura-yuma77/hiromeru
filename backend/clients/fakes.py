"""ローカル開発用の決定的な外部API Fake。Production/Previewでは使用しない。"""

import hashlib
import random
import uuid

from clients.x_api import XPostResult


class FakeEmbeddingClient:
    """同じ入力に同じ単位ベクトルを返す。"""

    def __init__(self, dimensions: int) -> None:
        """Embeddingの次元数を保持する。"""
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        """入力のHashをSeedにして決定的なEmbeddingを返す。"""
        seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")
        generator = random.Random(seed)  # noqa: S311
        values = [generator.uniform(-1.0, 1.0) for _ in range(self._dimensions)]
        norm = sum(value * value for value in values) ** 0.5
        return [value / norm for value in values]


class FakeXApiClient:
    """外部通信せず、Process内で一意な投稿IDを返す。"""

    async def post(self, text: str) -> XPostResult:
        """本文を外部へ送らず固定Prefixの投稿IDを返す。"""
        del text
        return XPostResult(x_post_id=f"fake-x-{uuid.uuid4().hex}")
