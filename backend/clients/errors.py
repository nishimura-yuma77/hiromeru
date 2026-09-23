"""外部APIのエラー。認証情報を含めず、自プロジェクトの例外へ変換する（BE_STD 8.3）。"""


class UpstreamError(Exception):
    """外部APIの呼び出し失敗の基底クラス。"""


class EmbeddingError(UpstreamError):
    """Embeddingを生成できなかった。"""


class Ga4ConfigurationError(UpstreamError):
    """GA4のCredential、Property、権限が不足または無効。"""


class Ga4ProviderError(UpstreamError):
    """GA4 Data APIで再試行対象外のProvider Errorが発生した。"""


class Ga4RetryableProviderError(Ga4ProviderError):
    """GA4 Data APIで一時的または応答検証の失敗が発生した。"""


class XApiConfigurationError(UpstreamError):
    """X APIのCredentialが不足または無効で、Requestを実行できない。"""


class XApiProviderError(UpstreamError):
    """X APIの読み取り処理で、再試行対象外のProvider Errorが発生した。"""


class XApiRetryableProviderError(XApiProviderError):
    """X APIの読み取り処理で、一時的なProvider障害が発生した。"""


class XApiRejectedError(UpstreamError):
    """X APIが投稿の失敗を確定して返した（4xx）。投稿されていないことが確実。"""

    def __init__(self, status_code: int) -> None:
        """失敗のHTTP Statusを保持する。"""
        super().__init__(f"X APIが投稿を拒否しました (status={status_code})")
        self.status_code = status_code


class XApiOutcomeUnknownError(UpstreamError):
    """X APIの結果を確定できなかった（5xx、タイムアウト、通信エラー、不正な応答）。

    投稿されている可能性があるため、自動で再投稿しない（BE_STD 8.3）。
    """
