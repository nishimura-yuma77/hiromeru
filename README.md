# Hiromeru

AI支援型Xマーケティングシステムです。アプリケーションはNext.jsとFastAPIで構成し、ローカルではDocker Compose、本番ではVercel ServicesとNeon PostgreSQLを使用します。

```text
Browser
  |
  v
Next.js
  | /api/*
  v
FastAPI
  |
  v
PostgreSQL
```

## Quick Start

必要なものはDockerです。

```bash
docker compose up --build
```

初回起動時にDB migrationが自動で適用されます。

| URL | 用途 |
| --- | --- |
| http://localhost:3000 | フロントエンドと各サービスの状態確認 |
| http://localhost:8000/api/health | FastAPIの死活確認 |
| http://localhost:8000/api/health/db | PostgreSQLの接続確認 |
| http://localhost:8000/api/docs | APIドキュメント |

終了する場合:

```bash
docker compose down
```

DBボリュームも削除する場合:

```bash
docker compose down --volumes
```

## Development

### Frontend

`frontend/app`を編集します。ブラウザから http://localhost:3000 を確認してください。APIへのリクエストは`/api/*`を使用します。

```bash
docker compose logs -f frontend
```

### Backend

`backend/`配下の各レイヤーを編集します。Uvicornのreloadが有効なため、変更は自動で反映されます。

```bash
docker compose logs -f backend
```

### Database Migration

モデル追加後にmigrationを作成します。

```bash
docker compose run --rm backend alembic revision --autogenerate -m "describe change"
docker compose run --rm migrate
```

## Directory Structure

| パス | 責務 |
| --- | --- |
| `frontend/` | Next.jsアプリケーション |
| `backend/api/` | HTTP境界、ルーター、Request/Responseスキーマ、認証依存 |
| `backend/services/` | 業務処理とトランザクション境界 |
| `backend/repositories/` | DBアクセスとSQL |
| `backend/models/` | DBテーブル定義 |
| `backend/domain/` | 外部ライブラリに依存しない業務ルール |
| `backend/clients/` | 外部APIアダプター |
| `backend/agents/` | Agent、Tool、Context構築 |
| `backend/core/` | 設定、ログ、エラー基底などの共通部品 |
| `backend/tests/unit/` | 単体テスト |
| `backend/tests/integration/` | 結合テスト |
| `backend/migrations/` | DB migration |
| `docker/frontend/Dockerfile` | Frontend開発イメージ |
| `docker/backend/Dockerfile` | Backendとmigrationの共通イメージ |
| `compose.yaml` | ローカル開発環境 |
| `vercel.json` | Vercel Servicesとルーティング |

## Verification

```bash
docker compose run --rm --no-deps frontend npm run lint
docker compose run --rm --no-deps frontend npm run build
docker compose run --rm --no-deps backend pytest
```

本番環境の準備は[DEPLOY.md](./DEPLOY.md)を参照してください。
