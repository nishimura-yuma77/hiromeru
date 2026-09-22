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

## Vercel Cron

施策評価は、ProductionでUTC 00:00に1日1回実行します。Endpoint、認証、冪等性、再試行の正本は`docs/v.0.1/CRON.md`です。

| 環境変数 | 用途 |
| --- | --- |
| `CRON_SECRET` | Vercel Cronから`GET /api/cron/post-metrics`を呼び出すBearer認証 |
| `CRON_METRIC_BATCH_SIZE` | 1回にClaimする投稿数。既定20 |
| `CRON_METRIC_MAX_ITEMS` | 1回の起動で処理する投稿数上限。既定100 |
| `CRON_METRIC_MAX_ATTEMPTS` | 指標取得の最大試行回数。既定3 |
| `CRON_MEMORY_BATCH_SIZE` | 1回に記憶生成用としてClaimする投稿数。既定20 |
| `CRON_MEMORY_MAX_ITEMS` | 1回の起動で記憶生成する投稿数上限。既定100 |
| `CRON_MEMORY_MAX_ATTEMPTS` | 評価記憶生成の最大試行回数。既定3 |

Cron設定はProduction Deploymentだけで有効にし、PreviewからProductionの計測処理を起動しないでください。

## Application Secrets

PreviewとProductionには、接続先を環境ごとに分離して次を設定します。

| 環境変数 | 用途 |
| --- | --- |
| `AUTH_COOKIE_SECRET` | 認証CookieとCSRF Tokenの署名鍵。環境ごとに異なる十分に長いランダム値 |
| `ALLOWED_ORIGINS` | CSRF検証で許可するカスタムOrigin。ワイルドカードは使用しない |
| `X_API_KEY` | X APIのConsumer Key |
| `X_API_KEY_SECRET` | X APIのConsumer Secret |
| `X_ACCESS_TOKEN` | 環境固定XアカウントのUser Access Token |
| `X_ACCESS_TOKEN_SECRET` | 環境固定XアカウントのUser Access Token Secret |
| `GA4_PROPERTY_ID` | 環境固定GA4 PropertyのID |
| `GA4_SERVICE_ACCOUNT_JSON` | GA4 Data API用Service Account認証情報 |

Productionは起動時にこれらの必須設定を検証します。FakeまたはMockの外部API Clientを明示的に使う開発・テスト環境だけは、XとGA4の実Credentialを省略できます。Secret値をBuild log、Runtime log、Response、Frontend環境変数へ出力しないでください。

## CI

`main`へのPull Requestでは次の処理が自動実行されます。

- Frontend lint
- Frontend production build
- Backend pytest
