# Deploy

## Vercel

1. GitHubの`hiromeru`リポジトリをVercelへimportします。
2. Root Directoryはリポジトリルートを選択します。
3. Framework Presetは`Services`を選択します。
4. Build CommandとOutput Directoryは設定せずにdeployします。

`vercel.json`により、`frontend/`はNext.js、`backend/`はFastAPIのVercel Functionとして構築されます。`/api/*`はbackend、それ以外はfrontendへルーティングされます。

Git連携後はPull RequestごとにPreview Deploymentが作成され、`main`へのmergeでProduction Deploymentが自動実行されます。

## Neon PostgreSQL

Vercel MarketplaceからNeonを追加し、Vercelプロジェクトへ接続します。環境変数はPreviewとProductionの両方へ設定してください。

| 環境変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | FastAPIが利用するpool接続URL |
| `DATABASE_URL_UNPOOLED` | Alembicが利用するdirect接続URL |

Neonが`postgresql://`形式で発行するURLは、アプリケーション内で`postgresql+psycopg://`へ変換されます。

## Production Migration

DB migrationはVercelの自動デプロイでは実行しません。複数のDeploymentから同時にmigrationが動くことを避けるため、GitHub Actionsから手動実行します。

1. GitHubリポジトリのEnvironmentに`production`を作成します。
2. Environment secret `NEON_DATABASE_URL_UNPOOLED`へNeonのdirect接続URLを設定します。
3. Actionsの`Production Migration`を`main`ブランチから実行します。

必要に応じて`production` Environmentへ承認ルールを設定してください。

## CI

`main`へのPull Requestでは次の処理が自動実行されます。

- Frontend lint
- Frontend production build
- Backend pytest
