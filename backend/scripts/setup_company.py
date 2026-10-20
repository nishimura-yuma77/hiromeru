"""会社と最初の責任者（管理ユーザー）を登録する初期設定スクリプト（REQUIREMENTS 2.6）。

使い方（`backend/` で実行する。接続先は環境変数 `DATABASE_URL` から読む）:

    python scripts/setup_company.py --company "株式会社サンプル" --name "山田太郎" \
        --email taro@example.com

パスワードは引数に渡さず、プロンプトで入力する（`--password-stdin` で標準入力からも渡せる）。
パスワードはArgon2でハッシュ化して保存し、ログにも出力しない。会社・責任者ユーザー・責任者の
adminsは同一トランザクションで登録し、メールアドレスが使用済みなら会社を含めて登録しない。
招待メールは送らず、責任者は作成直後から管理ユーザーとしてログインできる。
"""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

# `python scripts/setup_company.py` でも `backend/` 直下のモジュールを読めるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.container import build_default_context
from domain.accounts import normalize_email
from services.auth_service import AuthService, CompanySetupError


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="会社と最初の責任者を登録します。")
    parser.add_argument("--company", required=True, help="会社名")
    parser.add_argument("--name", required=True, help="責任者の表示名")
    parser.add_argument("--email", required=True, help="責任者のログイン用メールアドレス")
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
        user = await service.create_company(
            company_name=company, name=name, email=email, password=password
        )
    except CompanySetupError as error:
        raise SystemExit(f"登録しませんでした: {error}") from None
    return user.user_id


def main(argv: list[str] | None = None) -> None:
    """引数を解釈し、会社と責任者を登録して結果を表示する。"""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    password = _read_password(args.password_stdin)
    user_id = asyncio.run(_create(args.company, args.name, args.email, password))
    print(f"登録しました: user_id={user_id} email={normalize_email(args.email)}")


if __name__ == "__main__":
    main()
