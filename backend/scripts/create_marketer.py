"""会社・ユーザー・マーケターを1組作成する初期データ投入スクリプト。

使い方（`backend/` で実行する。接続先は環境変数 `DATABASE_URL` から読む）:

    python scripts/create_marketer.py --company "株式会社サンプル" --name "山田太郎" \
        --email taro@example.com

パスワードは引数に渡さず、プロンプトで入力する（`--password-stdin` で標準入力からも渡せる）。
パスワードはArgon2でハッシュ化して保存し、ログにも出力しない。
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from sqlalchemy.exc import IntegrityError

# `python scripts/create_marketer.py` でも `backend/` 直下のモジュールを読めるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.container import build_default_context
from services.auth_service import AuthService

_MIN_PASSWORD_LENGTH = 12


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="会社・ユーザー・マーケターを作成します。")
    parser.add_argument("--company", required=True, help="会社名")
    parser.add_argument("--name", required=True, help="マーケターの表示名")
    parser.add_argument("--email", required=True, help="ログインに使うメールアドレス")
    parser.add_argument(
        "--password-stdin", action="store_true", help="パスワードを標準入力の1行目から読む"
    )
    return parser.parse_args(argv)


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    password = getpass.getpass("パスワード: ")
    if getpass.getpass("パスワード（確認）: ") != password:
        raise SystemExit("パスワードが一致しません。")
    return password


async def _create(company: str, name: str, email: str, password: str) -> int:
    service = AuthService(build_default_context())
    try:
        record = await service.create_marketer(
            company_name=company, marketer_name=name, email=email, password=password
        )
    except IntegrityError:
        raise SystemExit("同じメールアドレスのユーザーが既に存在します。") from None
    return record.marketer_id


def main(argv: list[str] | None = None) -> None:
    """引数を解釈し、マーケターを作成して結果を表示する。"""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    password = _read_password(args.password_stdin)
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise SystemExit(f"パスワードは{_MIN_PASSWORD_LENGTH}文字以上にしてください。")
    marketer_id = asyncio.run(_create(args.company, args.name, args.email, password))
    print(f"作成しました: marketer_id={marketer_id} email={args.email.strip().lower()}")


if __name__ == "__main__":
    main()
