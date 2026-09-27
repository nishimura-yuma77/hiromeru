"""結果不明またはDB保存待ちのX投稿を復旧する運用Command。

出力はRequest ID、状態、日時などのMetadataだけに限定し、投稿Payloadは表示しない。
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# `python scripts/reconcile_x_posts.py` でも `backend/` 直下を読めるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.container import build_default_context
from domain.timefmt import format_utc, parse_aware_datetime
from services.x_post_recovery import XPostRecoveryError, XPostRecoveryService


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("正の整数を指定してください。")
    return parsed


def _aware_datetime(value: str) -> datetime:
    try:
        return parse_aware_datetime(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Timezone付きISO 8601日時を指定してください。") from None


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="未解決のX投稿を安全に照合・復旧します。")
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list", help="復旧対象の安全なMetadataを列挙")
    list_parser.add_argument("--limit", type=_positive_int, default=100)
    list_parser.add_argument("--company-id", type=_positive_int)

    inspect_parser = commands.add_parser("inspect", help="復旧対象の安全なMetadataを確認")
    inspect_parser.add_argument("--request-id", type=_positive_int, required=True)

    posted = commands.add_parser("resolve-posted", help="X公開済みとして結果不明を確定")
    posted.add_argument("--request-id", type=_positive_int, required=True)
    posted.add_argument("--x-post-id", required=True)
    posted.add_argument("--published-at", type=_aware_datetime, required=True)
    posted.add_argument(
        "--request-stdin",
        action="store_true",
        help="元Request JSONを標準入力から読み、保存済みHashと照合",
    )
    posted.add_argument("--execute", action="store_true")

    not_posted = commands.add_parser("resolve-not-posted", help="X未公開として結果不明を確定")
    not_posted.add_argument("--request-id", type=_positive_int, required=True)
    not_posted.add_argument("--execute", action="store_true")

    resume = commands.add_parser("resume", help="Xを呼ばず期限切れDB保存を再開")
    resume.add_argument("--request-id", type=_positive_int, required=True)
    resume.add_argument(
        "--request-stdin",
        action="store_true",
        help="元Request JSONを標準入力から読み、保存済みHashと照合",
    )
    resume.add_argument("--execute", action="store_true")
    return parser.parse_args(argv)


def _safe_json(value: Any) -> str:  # noqa: ANN401 - dataclass/listの安全なMetadataを受ける
    def default(item: object) -> str:
        if isinstance(item, datetime):
            return format_utc(item)
        raise TypeError

    return json.dumps(value, ensure_ascii=False, default=default, sort_keys=True)


def _request_from_stdin(enabled: bool) -> dict[str, Any] | None:
    """必要な場合だけ元Requestを標準入力から読み、表示せず返す。"""
    if not enabled:
        return None
    try:
        value = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError):
        raise XPostRecoveryError("stdin must contain one JSON object") from None
    if not isinstance(value, dict):
        raise XPostRecoveryError("stdin must contain one JSON object")
    return value


async def _run(args: argparse.Namespace) -> int:
    ctx = build_default_context()
    service = XPostRecoveryService(ctx)
    if args.command == "list":
        rows = await service.list_candidates(limit=args.limit, company_id=args.company_id)
        print(_safe_json([asdict(row) for row in rows]))
        return 0
    if args.command == "inspect":
        print(_safe_json(asdict(await service.inspect(args.request_id))))
        return 0
    if not args.execute:
        raise XPostRecoveryError("変更を実行するには --execute を指定してください")
    if (
        args.command in {"resolve-posted", "resume"}
        and ctx.settings.embedding_client_mode != "real"
    ):
        raise XPostRecoveryError("Embedding保存を伴うため EMBEDDING_CLIENT_MODE=real が必要です")
    if args.command == "resolve-posted":
        result = await service.resolve_posted(
            args.request_id,
            x_post_id=args.x_post_id,
            published_at=args.published_at,
            request_body=_request_from_stdin(args.request_stdin),
        )
    elif args.command == "resolve-not-posted":
        result = await service.resolve_not_posted(args.request_id)
    else:
        result = await service.resume_persistence(
            args.request_id, request_body=_request_from_stdin(args.request_stdin)
        )
    print(_safe_json(asdict(result)))
    return 0


def main(argv: list[str] | None = None) -> None:
    """引数を検証し、機密Payloadを表示せず運用復旧を実行する。"""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        exit_code = asyncio.run(_run(args))
    except XPostRecoveryError as error:
        # この例外は固定文言だけを持ち、Request Bodyや外部結果を含まない。
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:  # noqa: BLE001 - 運用出力へ例外内のPayloadを漏らさない
        print("error: recovery failed; no sensitive details were printed", file=sys.stderr)
        raise SystemExit(1) from None
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
