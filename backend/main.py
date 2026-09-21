"""Vercel Functions 用のエントリポイント。

アプリケーション本体は `backend/` 直下の各パッケージ（`api/` など）にある。
`backend/` をimportパスへ追加することをVercelが文書化していないため、
ここで明示的に追加してから `app` を公開する。
ローカルとDockerでは、このファイルを使わず `api.main:app` を直接起動する。

`backend/` のパスは実行時に追加するため、エディタ（Pylance・pyright）の設定に関係なく
解決できるよう、`import_module` で読み込み、型は `FastAPI` として明示する。
"""

import sys
from importlib import import_module
from pathlib import Path

from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent))

app: FastAPI = import_module("api.main").app

__all__ = ["app"]
