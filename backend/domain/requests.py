"""リクエストBodyのスキーマ（API_DESIGN 2.2）。型・必須・長さを検証する。

すべて strict とし、数値から文字列への暗黙の変換や、未定義のフィールドを受け付けない。
`company_id` や `marketer_id` はクライアント入力を使わないため、フィールドを持たない。
"""

from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

from domain.constants import (
    MAX_CAMPAIGN_TEXT_LENGTH,
    MAX_CAMPAIGN_TITLE_LENGTH,
    MAX_LANDING_URL_LENGTH,
)
from domain.timefmt import parse_aware_datetime


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("ISO 8601の文字列が必要です")
    return parse_aware_datetime(value)


AwareDatetime = Annotated[datetime, BeforeValidator(_parse_datetime)]
PositiveId = Annotated[int, Field(gt=0)]
Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CAMPAIGN_TITLE_LENGTH),
]
LongText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_CAMPAIGN_TEXT_LENGTH)
]


class StrictModel(BaseModel):
    """未定義のフィールドと型の暗黙変換を許さない基底モデル。"""

    model_config = ConfigDict(strict=True, extra="forbid")


class LoginRequest(StrictModel):
    """ログイン。パスワードは長さだけを制限する（DoS対策）。"""

    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class CampaignFields(StrictModel):
    """施策の編集可能な5項目。"""

    title: Title
    target_profile: LongText
    background: LongText
    objective: LongText
    plan: LongText


class CampaignEditRequest(CampaignFields):
    """施策編集（4.2）。`expected_updated_at` は必須。"""

    expected_updated_at: AwareDatetime


class CampaignUpsertRequest(CampaignFields):
    """施策の登録・更新（4.1）。`id` があれば上書き、なければ新規作成。"""

    id: PositiveId | None = None
    expected_updated_at: AwareDatetime | None = Field(default=None, validate_default=True)

    @field_validator("expected_updated_at")
    @classmethod
    def _check_expected_updated_at(
        cls, value: datetime | None, info: ValidationInfo
    ) -> datetime | None:
        """上書きでは `expected_updated_at` が必須。新規作成では指定しない。"""
        del cls
        campaign_id = info.data.get("id")
        if campaign_id is not None and value is None:
            raise ValueError("上書きには expected_updated_at が必要です")
        if campaign_id is None and value is not None:
            raise ValueError("新規作成では expected_updated_at を指定できません")
        return value


class XPostRequest(StrictModel):
    """X投稿の公開（3.1）。"""

    campaign_id: PositiveId
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    landing_url: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_LANDING_URL_LENGTH),
    ]


class MessageRequest(StrictModel):
    """メッセージ送信（5.3）。上限の文字数は設定値のため、サービスで検証する。"""

    message: str
