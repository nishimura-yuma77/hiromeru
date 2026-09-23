# Deploy

## Vercel

1. GitHubの`hiromeru`リポジトリをVercelへimportします。
2. Root Directoryはリポジトリルートを選択します。
3. Framework Presetは`Services`を選択します。
4. Build CommandとOutput Directoryは設定せずにdeployします。

`vercel.json`により、`frontend/`はNext.js、`backend/`はFastAPIのVercel Functionとして構築されます。`/api/*`はbackend、それ以外はfrontendへルーティングされます。

- backendのエントリポイントは`backend/main.py`です。アプリケーション本体は`backend/`直下（`api/`、`services/`など）にあり、`main.py`が`backend/`をimportパスへ追加して`app`を公開します（Vercelがimportパスを文書化していないため）。
- backendの`maxDuration`は、`vercel.json`の`services.backend.functions`で300秒（Hobbyの上限）に明示しています。プランを変更する場合は、この値と冪等性のLease（`API_DESIGN.md`の2.3）を見直してください。
- backendの依存関係は`pyproject.toml`で宣言し、`uv.lock`で固定します。Vercelは`uv.lock`を検出して`uv`で依存関係を復元します。
- PreviewとProductionでは`EXTERNAL_CLIENT_MODE=real`と`COOKIE_SECURE=true`を設定します。`fake`はローカル開発とテスト専用です。
- Preview Deploymentで、`/api/health`と`/api/health/db`が応答することを確認してください。

Git連携後はPull RequestごとにPreview Deploymentが作成され、`main`へのmergeでProduction Deploymentが自動実行されます。

## Neon PostgreSQL

Vercel MarketplaceからNeonを追加し、Vercelプロジェクトへ接続します。環境変数はPreviewとProductionの両方へ設定してください。

| 環境変数 | 用途 |
| --- | --- |
| `DATABASE_URL` | FastAPIが利用するpool接続URL |
| `DATABASE_URL_UNPOOLED` | Alembicが利用するdirect接続URL |

Neonが`postgresql://`形式で発行するURLは、アプリケーション内で`postgresql+psycopg://`へ変換されます。

### Preview Branch Cleanup

Neon Freeは1プロジェクトにつき10ブランチまでです。Vercel Managed Integrationが作成するPreviewブランチは、GitブランチやPRではなくVercel Preview Deploymentの削除に連動して削除されます。不要なDeploymentが残ると`Resource provisioning failed`で新しいPreviewを作成できなくなります。

`.github/workflows/cleanup-preview.yml`は、同一リポジトリ内のPRが閉じられたとき、そのheadブランチに対応するVercel Preview Deploymentを削除します。Production DeploymentとFork元のブランチは対象にしません。Deploymentの削除により、Neon側のPreviewブランチ削除も発火します。

Repository settingsへ次を設定してください。

| 種別 | 名前 | 値 |
| --- | --- | --- |
| Actions secret | `VERCEL_PREVIEW_CLEANUP_TOKEN` | Vercelで発行した`hiromeru`プロジェクト限定Token |
| Actions variable | `VERCEL_PROJECT_ID` | Vercel Project ID |
| Actions variable | `VERCEL_TEAM_ID` | Vercel Team ID |

TokenはVercel DashboardのAccount Settingsから発行し、リポジトリやログへ値を保存しないでください。Secretが未設定の場合、Cleanup Workflowは設定漏れを見逃さないよう失敗します。

## Production Migration

DB migrationはVercelの自動デプロイでは実行しません。複数のDeploymentから同時にmigrationが動くことを避けるため、GitHub Actionsから手動実行します。

1. GitHubリポジトリのEnvironmentに`production`を作成します。
2. Environment secret `NEON_DATABASE_URL_UNPOOLED`へNeonのdirect接続URLを設定します。
3. Actionsの`Production Migration`を`main`ブランチから実行します。

必要に応じて`production` Environmentへ承認ルールを設定してください。
Alembicは`DATABASE_URL_UNPOOLED`がない場合に起動を中止し、`DATABASE_URL`へFallbackしません。

## Campaign Embedding Backfill

検索Projectionを変更した場合は、対応コードをProductionへデプロイした後、`backend/`から次のCommandを手動実行します。

```bash
python scripts/backfill_campaign_embeddings.py --execute
```

`DATABASE_URL`、`EXTERNAL_CLIENT_MODE=real`、OrcaRouter設定が必要です。`--batch-size`、`--max-items`、`--company-id`で対象を制限でき、出力された`last_id`を`--after-id`へ渡すと途中から再開できます。失敗または実行中の編集との競合が残った場合は終了Code 1になり、同じCommandを再実行するとHashが一致する更新済みデータはスキップされます。

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

## X Post Operational Recovery

X投稿結果が不明なRequestと、X成功後にDB保存待ちでLeaseが切れたRequestは、公開HTTP APIではなく`backend/`の運用Commandで復旧します。まず安全なMetadataだけを確認します。

```bash
python scripts/reconcile_x_posts.py list --company-id 123
python scripts/reconcile_x_posts.py inspect --request-id 456
```

`manual_reconciliation`はX管理画面で投稿有無を確認してから、次のどちらか一方を一度だけ実行します。公開日時はX上の実日時をTimezone付きISO 8601で指定します。

```bash
python scripts/reconcile_x_posts.py resolve-posted \
  --request-id 456 --x-post-id 1234567890 \
  --published-at 2026-09-23T09:30:00Z --execute
python scripts/reconcile_x_posts.py resolve-not-posted --request-id 456 --execute
```

`resume_persistence`はXへ再投稿せず、保存済みの外部結果を再検証してDB保存だけを再開します。

```bash
python scripts/reconcile_x_posts.py resume --request-id 789 --execute
```

`resolve-posted`と`resume`は本番Embeddingを作るため`EXTERNAL_CLIENT_MODE=real`およびOrcaRouter設定が必要です。Command出力へCredential、Request Body、X本文、Tracked URL、Provider Body、Lease Tokenは含まれません。`resolve-*`はPost関連データ、確定Replay Response、冪等状態、新しい完了済み監査Turnを1つのTransactionで保存します。競合時は一方だけが成功します。実行前に接続先の`DATABASE_URL`を確認し、まず`inspect`したRequest IDだけを対象にしてください。

元Requestの本文またはURLが履歴保存時の機密情報マスク対象だった場合、自動復元は安全側で拒否されます。その場合だけ、元のJSON Object（`campaign_id`、`body`、`landing_url`）を標準入力から渡します。内容は保存済みRequest Hashと一致しなければ拒否され、出力・ログ・監査Turnには記録されません。Shell引数には本文を指定しないでください。

```bash
python scripts/reconcile_x_posts.py resolve-posted \
  --request-id 456 --x-post-id 1234567890 \
  --published-at 2026-09-23T09:30:00Z --request-stdin --execute < original-request.json
python scripts/reconcile_x_posts.py resume \
  --request-id 789 --request-stdin --execute < original-request.json
```

## Application Secrets

PreviewとProductionには、接続先を環境ごとに分離して次を設定します。

| 環境変数 | 用途 |
| --- | --- |
| `AUTH_COOKIE_SECRET` | 認証CookieとCSRF Tokenの署名鍵。環境ごとに異なる十分に長いランダム値 |
| `ALLOWED_ORIGINS` | CSRF検証で許可するカスタムOrigin。ワイルドカードは使用しない |
| `EXTERNAL_CLIENT_MODE` | Preview・Productionは`real`。ローカル開発・テストは`fake` |
| `ORCAROUTER_BASE_URL` | OrcaRouter APIのBase URL |
| `ORCAROUTER_API_KEY` | OrcaRouter APIの認証鍵 |
| `ORCAROUTER_FIREWALL_API_KEY` | Agent Firewall専用のgateway-scoped認証鍵 |
| `AGENT_MODEL` | Chat Completionsで使う明示的なモデル名 |
| `AGENT_MAX_STEPS` | 親Turnと子Agentで共有する論理step上限。既定20 |
| `AGENT_MAX_COST_USD` | 親Turn単位の確定USD cost上限。既定1.00000000 |
| `LLM_TIMEOUT_SECONDS` | 1回のLLM request timeout。既定60秒 |
| `LLM_MAX_OUTPUT_TOKENS` | 1回のLLM最大出力token。既定4096 |
| `GENERATION_LOOKUP_ATTEMPTS` | 確定cost取得のbounded retry回数。既定3 |
| `GENERATION_LOOKUP_BACKOFF_SECONDS` | 確定cost取得retryの基準待機秒。既定0.1 |
| `X_API_KEY` | X APIのConsumer Key |
| `X_API_KEY_SECRET` | X APIのConsumer Secret |
| `X_ACCESS_TOKEN` | 環境固定XアカウントのUser Access Token |
| `X_ACCESS_TOKEN_SECRET` | 環境固定XアカウントのUser Access Token Secret |
| `GA4_PROPERTY_ID` | 環境固定GA4 PropertyのID |
| `GA4_SERVICE_ACCOUNT_JSON` | GA4 Data API用Service Account認証情報 |

PreviewとProductionは起動時にこれらの必須設定を検証し、Productionでは`CRON_SECRET`も必須です。FakeまたはMockの外部API Clientを明示的に使う開発・テスト環境だけは、OrcaRouter、X、GA4の実Credentialを省略できます。Secret値をBuild log、Runtime log、Response、Frontend環境変数へ出力しないでください。

実Agent RunnerはOrcaRouter Chat Completionsを使用し、SDK tracingを無効化したうえで履歴、Tool loop、budget、永続化をアプリケーションが管理します。

## CI

`main`へのPull Requestでは次の処理が自動実行されます。

- Frontend lint
- Frontend production build
- Backend pytest
