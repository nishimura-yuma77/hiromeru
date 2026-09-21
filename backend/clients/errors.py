"""外部APIのエラー。認証情報を含めず、自プロジェクトの例外へ変換する（BE_STD 8.3）。"""


class UpstreamError(Exception):
    """外部APIの呼び出し失敗の基底クラス。"""


class EmbeddingError(UpstreamError):
    """Embeddingを生成できなかった。"""


class XApiRejectedError(UpstreamError):
    """X APIが投稿の失敗を確定して返した（4xx）。投稿されていないことが確実。"""

    def __init__(self, status_code: int) -> None:
        """失敗のHTTP Statusを保持する。429 のときだけ再試行可能とする。"""
        super().__init__(f"X APIが投稿を拒否しました (status={status_code})")
        self.status_code = status_code

    @property
    def retryable(self) -> bool:
        """再試行できるか（429 のみ）。"""
        return self.status_code == 429


class XApiOutcomeUnknownError(UpstreamError):
    """X APIの結果を確定できなかった（5xx、タイムアウト、通信エラー、不正な応答）。

    投稿されている可能性があるため、自動で再投稿しない（BE_STD 8.3）。
    """
