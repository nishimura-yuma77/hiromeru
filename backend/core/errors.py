"""業務エラー。エラーコードは API_DESIGN 10章に登録されたものだけを使う（BE_STD 8章）。"""

from typing import Final, Literal, TypedDict

type FieldErrorCode = Literal[
    "REQUIRED", "TOO_LONG", "INVALID_FORMAT", "INVALID_URL", "X_LENGTH_EXCEEDED"
]


class FieldError(TypedDict):
    """入力Fieldへ対応付けられる、Frontend向けの安定したError。"""

    field: str | None
    code: FieldErrorCode
    message: str


# code -> (HTTP Status, 再試行可否)。API_DESIGN 10章の一覧と1対1に対応させる。
ERROR_SPECS: Final[dict[str, tuple[int, bool]]] = {
    # 共通
    "INVALID_ARGUMENT": (400, False),
    "INVALID_IDEMPOTENCY_KEY": (400, False),
    "UNAUTHENTICATED": (401, False),
    "INVALID_CREDENTIALS": (401, False),
    "CSRF_VALIDATION_FAILED": (403, True),
    "AGENT_SESSION_NOT_FOUND": (404, False),
    "IDEMPOTENCY_REQUEST_IN_PROGRESS": (409, True),
    "IDEMPOTENCY_KEY_REUSED": (409, False),
    "EMBEDDING_FAILED": (500, True),
    "INTERNAL_ERROR": (500, True),
    # Agent会話
    "AGENT_SESSION_SAVE_FAILED": (500, True),
    "AGENT_TURN_NOT_FOUND": (404, False),
    "TURN_IN_PROGRESS": (409, True),
    "TURN_BLOCKED": (422, False),
    "TURN_STEP_LIMIT_EXCEEDED": (422, False),
    "TURN_COST_LIMIT_EXCEEDED": (422, False),
    "TURN_TIME_LIMIT_EXCEEDED": (504, True),
    "CONTEXT_COMPACTION_FAILED": (500, True),
    "AGENT_EXECUTION_FAILED": (500, True),
    "TURN_INTERRUPTED": (500, True),
    # 施策・投稿・記憶
    "CAMPAIGN_NOT_FOUND": (404, False),
    "CAMPAIGN_ARCHIVED": (409, False),
    "CAMPAIGN_CONFLICT": (409, False),
    "INVALID_CAMPAIGN": (422, False),
    "CAMPAIGN_SAVE_FAILED": (500, True),
    "CAMPAIGN_UPDATE_FAILED": (500, True),
    "POST_NOT_FOUND": (404, False),
    "X_POST_UNRESOLVED": (409, False),
    "INVALID_X_POST": (422, False),
    "X_POST_FAILED": (502, False),  # 429 のときだけ再試行可能（条件付き）
    "X_POST_OUTCOME_UNKNOWN": (504, False),
    "X_POST_SAVE_FAILED": (500, True),
    "MEMORY_NOT_FOUND": (404, False),
    "MEMORY_DELETE_FAILED": (500, True),
}

# 利用者向けの既定メッセージ。内部情報を含めない。
DEFAULT_MESSAGES: Final[dict[str, str]] = {
    "INVALID_ARGUMENT": "リクエストの内容が正しくありません。",
    "INVALID_IDEMPOTENCY_KEY": "Idempotency-Key が指定されていないか、UUID形式ではありません。",
    "UNAUTHENTICATED": "ログインしてください。",
    "INVALID_CREDENTIALS": "メールアドレスまたはパスワードが正しくありません。",
    "CSRF_VALIDATION_FAILED": "リクエストを検証できませんでした。画面を再読み込みしてください。",
    "AGENT_SESSION_NOT_FOUND": "会話が見つかりません。",
    "IDEMPOTENCY_REQUEST_IN_PROGRESS": "同じ操作を処理中です。しばらくしてから再送してください。",
    "IDEMPOTENCY_KEY_REUSED": "同じ Idempotency-Key が別の内容で使用されています。",
    "EMBEDDING_FAILED": "検索用のEmbeddingを生成できませんでした。",
    "INTERNAL_ERROR": "内部エラーが発生しました。",
    "AGENT_SESSION_SAVE_FAILED": "会話を保存できませんでした。",
    "AGENT_TURN_NOT_FOUND": "ターンが見つかりません。",
    "TURN_IN_PROGRESS": "前の処理が実行中です。完了してから再送してください。",
    "TURN_BLOCKED": "入力が安全性の検査でブロックされました。",
    "TURN_STEP_LIMIT_EXCEEDED": "処理のステップ数の上限に達しました。",
    "TURN_COST_LIMIT_EXCEEDED": "処理のコストの上限に達しました。",
    "TURN_TIME_LIMIT_EXCEEDED": "処理時間の上限に達しました。",
    "CONTEXT_COMPACTION_FAILED": "会話の履歴を圧縮できませんでした。",
    "AGENT_EXECUTION_FAILED": "Agentの実行を継続できませんでした。",
    "TURN_INTERRUPTED": "処理が中断されました。同じ依頼を再送してください。",
    "CAMPAIGN_NOT_FOUND": "施策が見つかりません。",
    "CAMPAIGN_ARCHIVED": "Archive済みの施策は変更できません。",
    "CAMPAIGN_CONFLICT": "施策が別の操作で更新されています。最新の内容を確認してください。",
    "INVALID_CAMPAIGN": "施策の内容が条件を満たしていません。",
    "CAMPAIGN_SAVE_FAILED": "施策を保存できませんでした。",
    "CAMPAIGN_UPDATE_FAILED": "施策を更新できませんでした。",
    "POST_NOT_FOUND": "投稿が見つかりません。",
    "X_POST_UNRESOLVED": "同じ内容の投稿が処理中、または結果不明のため、投稿できません。",
    "INVALID_X_POST": "投稿の内容が条件を満たしていません。",
    "X_POST_FAILED": "Xへの投稿に失敗しました。",
    "X_POST_OUTCOME_UNKNOWN": "Xへの投稿結果を確定できません。Xの管理画面で確認してください。",
    "X_POST_SAVE_FAILED": "Xへは投稿済みですが、保存に失敗しました。同じキーで再送してください。",
    "MEMORY_NOT_FOUND": "記憶が見つかりません。",
    "MEMORY_DELETE_FAILED": "記憶を削除できませんでした。",
}


class AppError(Exception):
    """業務エラーの基底クラス。

    `message` には、利用者に返せるマスク済みの文言だけを入れる。
    """

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        agent_turn_id: int | None = None,
        retryable: bool | None = None,
        retry_after_seconds: int | None = None,
        field_errors: list[FieldError] | None = None,
    ) -> None:
        """エラーを作る。

        Args:
            code: API_DESIGN 10章に登録されたエラーコード。
            message: 利用者向けの説明。省略時は既定のメッセージを使う。
            agent_turn_id: 履歴へ保存したTurnのID。保存しないエラーでは None。
            retryable: 再試行可否。省略時はコードの既定値を使う（X_POST_FAILED のみ上書きする）。
            retry_after_seconds: `Retry-After` ヘッダーに設定する秒数。
            field_errors: 入力FieldごとのError。入力以外のErrorでは空配列。

        Raises:
            ValueError: 未登録のエラーコードが指定された場合。
        """
        if code not in ERROR_SPECS:
            raise ValueError(f"未登録のエラーコードです: {code}")
        status_code, default_retryable = ERROR_SPECS[code]
        text = message or DEFAULT_MESSAGES[code]
        super().__init__(text)
        self.code = code
        self.message = text
        self.status_code = status_code
        self.retryable = default_retryable if retryable is None else retryable
        self.agent_turn_id = agent_turn_id
        self.retry_after_seconds = retry_after_seconds
        self.field_errors = list(field_errors or [])

    def serialize(self) -> dict[str, object]:
        """APIの共通Error Objectへ変換する。"""
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "agent_turn_id": self.agent_turn_id,
            "field_errors": self.field_errors,
        }


class LeaseLostError(Exception):
    """冪等性レコードの実行権（Lease・Fencing Token）を失った。

    最終Transactionで実行Tokenまたは期限が一致しないときに送出する（API_DESIGN 2.3）。
    """


def error_spec(code: str) -> tuple[int, bool]:
    """エラーコードの (HTTP Status, 再試行可否) を返す。"""
    return ERROR_SPECS[code]
