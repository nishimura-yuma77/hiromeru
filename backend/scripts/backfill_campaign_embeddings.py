"""既存Campaignの検索Embeddingを現行Projectionで再生成する運用Command。

使い方（`backend/` で実行する。外部Clientはreal modeに設定する）:

    python scripts/backfill_campaign_embeddings.py --execute

`--after-id`と出力される`last_id`を使って途中から再開できる。
"""

import argparse
import asyncio
import sys
from pathlib import Path

# `python scripts/backfill_campaign_embeddings.py` でも `backend/` 直下を読めるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.container import build_default_context
from services.campaign_embedding_backfill import CampaignEmbeddingBackfillService


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("正の整数を指定してください。")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("0以上の整数を指定してください。")
    return parsed


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Campaign検索Embeddingを再生成します。")
    parser.add_argument("--execute", action="store_true", help="DB更新とEmbedding API呼出しを許可")
    parser.add_argument("--batch-size", type=_positive_int, default=100, help="一度に読む件数")
    parser.add_argument(
        "--after-id", type=_non_negative_int, default=0, help="再開位置のCampaign ID"
    )
    parser.add_argument("--max-items", type=_positive_int, help="今回処理する最大件数")
    parser.add_argument("--company-id", type=_positive_int, help="対象を会社IDで限定")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    ctx = build_default_context()
    if ctx.settings.embedding_client_mode != "real":
        raise SystemExit("実Embeddingを保存するためEMBEDDING_CLIENT_MODE=realが必要です。")
    result = await CampaignEmbeddingBackfillService(ctx).run(
        batch_size=args.batch_size,
        after_id=args.after_id,
        max_items=args.max_items,
        company_id=args.company_id,
    )
    print(
        f"完了: scanned={result.scanned} updated={result.updated} "
        f"unchanged={result.unchanged} conflicted={result.conflicted} "
        f"failed={result.failed} last_id={result.last_id}"
    )
    return 1 if result.conflicted or result.failed else 0


def main(argv: list[str] | None = None) -> None:
    """引数を検証してBackfillを実行する。"""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if not args.execute:
        raise SystemExit("実行するには--executeを指定してください。")
    exit_code = asyncio.run(_run(args))
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
