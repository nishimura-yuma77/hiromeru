# marketer_id → user_id 移行 影響範囲

`marketers` テーブルを廃止して `users` へ統合し、業務操作主体・作成者・会話履歴の所有者を `users.id`（`user_id` / `created_by_user_id`）で表す変更の影響範囲をまとめる。正本のスキーマは [DATABASE.dbml](./DATABASE.dbml) とする。

前提: `feature/company-user-management` のユーザー管理設計（`admins`・`emails`・`invitations`・`users.status`・`users.auth_generation`）を取り込んだうえでの変更とする。同設計の「DBのデータは初期化して再投入し、既存データの移行は行わない」方針を引き継ぐため、データ移行（marketer_id → user_id の値変換）は行わない。

## 1. 変更しないもの

- 役割名としての「マーケター」。`admins` を持たないユーザーを「マーケター（ユーザー）」と呼ぶ
- API の `user_type: "admin" | "marketer"`、入口ヒントCookie `hiromeru_login_portal` の値 `marketer`
- 画面・ルーティング上の「マーケター向け画面」という区分
- `emails`・`invitations` の `user_id`（もともと `users.id` を参照）

## 2. DBスキーマ

### 2.1 テーブル・カラム

| テーブル | 変更前 | 変更後 | 備考 |
|---|---|---|---|
| `marketers` | テーブル | **削除** | `name`・`company_id` は `users` へ移す |
| `users` | — | `company_id bigint not null` を追加 | `companies.id` を参照（restrict）。作成後に変更しない |
| `users` | — | `name varchar(255) not null` を追加 | 旧 `marketers.name`（表示名） |
| `users` | — | `UNIQUE (id, company_id)`、`INDEX (company_id)` を追加 | 複合外部キーの参照先 |
| `admins` | `(user_id, company_id) → marketers.(user_id, company_id)` | `(user_id, company_id) → users.(id, company_id)` | 単独の `admins.user_id → users.id` は複合FKに包含されるため削除 |
| `campaigns` | `created_by_marketer_id → marketers.id` | `created_by_user_id`、`(created_by_user_id, company_id) → users.(id, company_id)` | 作成者と施策の会社一致をDBで保証（制約の強化） |
| `posts` | `created_by_marketer_id → marketers.id` | `created_by_user_id`、`(created_by_user_id, company_id) → users.(id, company_id)` | 同上 |
| `api_list_snapshots` | `marketer_id → marketers.id`（cascade） | `user_id → users.id`（cascade） | |
| `agent_sessions` | `marketer_id → marketers.id` | `user_id → users.id` | |
| `api_idempotency_requests` | `marketer_id → marketers.id` | `user_id → users.id` | |

### 2.2 インデックス・制約名（コード／migration上の名前）

| 現在の名前 | 定義（変更後） | 変更後の名前（案） |
|---|---|---|
| `uq_agent_sessions_id_marketer` | `UNIQUE (id, user_id)` | `uq_agent_sessions_id_user` |
| `ix_agent_sessions_marketer_updated` | `(user_id, updated_at)` | `ix_agent_sessions_user_updated` |
| （自動命名）親Session複合FK | `(parent_session_id, user_id) → agent_sessions.(id, user_id)` | 名前を明示する |
| `uq_air_marketer_op_key` | `UNIQUE (user_id, operation, idempotency_key)` | `uq_air_user_op_key` |
| `fk_air_session_marketer` | `(session_id, user_id) → agent_sessions.(id, user_id)` | `fk_air_session_user` |
| `ix_air_marketer_op_hash` | `(user_id, operation, request_hash)` | `ix_air_user_op_hash` |
| `ix_api_list_snapshots_owner_resource_expiry` | `(user_id, resource, expires_at)` | 変更不要 |
| `api_list_snapshots_marketer_id_fkey`（自動命名） | `user_id → users.id` | `api_list_snapshots_user_id_fkey` |

`ix_air_marketer_op_hash` は従来コードにだけ存在し DBML に記載がなかったため、今回 DBML に追加した。

### 2.3 不変条件の変化

- 「業務データを操作する主体は、データを所有する会社に所属する」は、`campaigns`・`posts` の作成者について複合FKでDB保証になった。`agent_sessions`・`api_idempotency_requests` は `company_id` を持たないため、従来どおり `users.company_id` 経由でアプリケーションが判定する
- 「1ユーザーにマーケタープロファイル1件」「管理ユーザーも本人のmarketersを必須」という制約は不要になった（行自体が存在しない）
- 種別変更（admin ⇄ marketer）は `admins` の追加・削除だけになり、会話履歴・作成者の `user_id` は不変
- `users.company_id` を変更しないことはアプリケーションで保証する（DBでは複合FKの `ON UPDATE` 既定 NO ACTION により、参照行がある間は実質変更不可）

## 3. migration

- 既存 `0001`〜`0003` は適用済み環境（本番・Preview）があるため書き換えず、新リビジョン `0004_users_absorb_marketers` を追加する
- データは初期化・再投入する方針のため、`0004` は「業務テーブルを空にしてから構造を変える」前提でよい。手順:
  1. `users` に `company_id`・`name` を追加（既存行があれば `marketers` から埋め、NOT NULL 化）
  2. `users (id, company_id)` の一意制約を作成
  3. 各テーブルで `marketer_id` / `created_by_marketer_id` を `user_id` / `created_by_user_id` にリネームし、値を `marketers.user_id` へ変換、FK・一意制約・インデックスを張り替え
  4. `admins` の複合FKを `users` 参照へ張り替え
  5. `marketers` を削除
- `downgrade` は逆手順で実装する（または「データ初期化前提のため非対応」と明記する。チームで決める）
- `.github/workflows/migrate-production.yml` は変更不要だが、本番適用前にDB初期化手順と順序を合わせる

## 4. バックエンド

| 区分 | ファイル | 影響 |
|---|---|---|
| モデル | [models/identity.py](../../backend/models/identity.py) | `Marketer` 削除、`User` に `company_id`・`name` と `UniqueConstraint(id, company_id)` を追加 |
| モデル | [models/campaign.py](../../backend/models/campaign.py)、[models/post.py](../../backend/models/post.py) | `created_by_user_id` と複合FK |
| モデル | [models/agent.py](../../backend/models/agent.py)、[models/idempotency.py](../../backend/models/idempotency.py)、[models/snapshot.py](../../backend/models/snapshot.py) | `user_id` と制約名（2.2） |
| 認証 | [core/security.py](../../backend/core/security.py) | Cookie / CSRF ペイロードのキー `m`（marketer_id）を user_id に。ユーザー管理ブランチで `user_id`＋`auth_generation` 化する設計と合わせる。デプロイ時に既存Cookieは無効になる（再ログイン） |
| 認証 | [api/deps.py](../../backend/api/deps.py)、[api/routers/auth.py](../../backend/api/routers/auth.py) | 認証主体の取得、レスポンスの `marketer_id` 削除 |
| Context | [services/context.py](../../backend/services/context.py) | `AuthContext.marketer_id` を削除し `user_id` に一本化（生成箇所5か所） |
| Repository | [repositories/identity.py](../../backend/repositories/identity.py) | `MarketerRecord`・`get_marketer`・`create_marketer` を `users` ベースへ。`users` と `marketers` の JOIN が不要になる |
| Repository | [repositories/agent.py](../../backend/repositories/agent.py)、[repositories/idempotency.py](../../backend/repositories/idempotency.py)、[repositories/snapshots.py](../../backend/repositories/snapshots.py)、[repositories/campaigns.py](../../backend/repositories/campaigns.py)、[repositories/posts.py](../../backend/repositories/posts.py) | 所有者条件・作成者カラムの置換 |
| Service | [services/x_post_recovery.py](../../backend/services/x_post_recovery.py) | `Marketer` から会社を引いていた処理を `User.company_id` へ。`AuthContext` の再構築も変更 |
| Service | `services/` の auth / approval / campaign / campaign_approval / memory / metrics / post / session / turn / x_post_approval | 引数・ログ項目の `marketer_id` を `user_id` へ |
| Agent runtime | [agent_runtime/executor.py](../../backend/agent_runtime/executor.py)、[proposal_tools.py](../../backend/agent_runtime/proposal_tools.py)、[runner.py](../../backend/agent_runtime/runner.py)、[tools.py](../../backend/agent_runtime/tools.py) | 実行Contextの `marketer_id` を `user_id` へ |
| Domain | [domain/requests.py](../../backend/domain/requests.py) | docstring のみ |
| Script | [scripts/create_marketer.py](../../backend/scripts/create_marketer.py) | ユーザー管理設計で初期設定スクリプトに置き換え予定。users への name・company_id 登録に合わせる |
| Script | [scripts/demo_dataset.py](../../backend/scripts/demo_dataset.py) | 投入データの `marketers` 行と `marketer_id` を削除・置換 |
| 構造化ログ | 各 Service | ログキー `marketer_id` を `user_id` へ。ダッシュボードや検索クエリがあれば追随する |

## 5. テスト

- [tests/conftest.py](../../backend/tests/conftest.py)、[tests/support/client.py](../../backend/tests/support/client.py): fixture の `create_marketer`・`marketer_id`
- `tests/integration/` の約20ファイル（agent_context / agent_sessions / auth / business_tools / clarification / metrics_pagination / posts_reference / proposal_tools / real_agent_runner / tool_executor / turn_projection / turn_recovery / web_tools / x_post / x_post_recovery ほか）
- [test_cron_snapshot_migration.py](../../backend/tests/integration/test_cron_snapshot_migration.py): FK名 `api_list_snapshots_marketer_id_fkey` と `marketers` 前提のアサーション。`0004` の migration テストを追加する
- [test_create_marketer_script.py](../../backend/tests/integration/test_create_marketer_script.py): スクリプト置き換えに合わせて改修
- `tests/unit/` の test_agent_tools.py、test_web_tools.py
- 追加すべきテスト: 別会社のユーザーを `created_by_user_id` に指定した `campaigns`・`posts` の INSERT が FK違反になること

## 6. フロントエンド

| ファイル | 影響 |
|---|---|
| [features/auth/types/auth.ts](../../frontend/features/auth/types/auth.ts) | `marketer_id` の検証・`marketerId` を `user_id` / `userId` へ |
| [features/auth/server/getCurrentMarketer.ts](../../frontend/features/auth/server/getCurrentMarketer.ts) | `getCurrentUser` などへ改名（任意） |
| [app/(authenticated)/layout.tsx](../../frontend/app/(authenticated)/layout.tsx) | 上記の呼び出し |

## 7. ドキュメント（反映済み）

次の設計書の `marketers`・`marketer_id` の記述を、本変更に合わせて `users`・`user_id` へ更新した。

- API_DESIGN.md: 共通方針、2.8 認証、ログイン・`/auth/me` のResponse（`marketer_id` を削除し、ログイン成功時は `user_id` を返す。「マーケタープロファイルがない場合」の失敗条件を削除）、構造化ログ、Session作成、ユーザー管理API
- USECASE.md、REQUIREMENTS.md、E2E_TEST_SPEC.md、SCREEN_DESIGN.md、AGENT_DESIGN.md、backend/CODING_STANDARDS.md

## 8. 未決事項

- `0004` の `downgrade` を実装するか
- 構造化ログのキー変更に伴う、既存ログ検索・アラート設定の有無
- ユーザー管理ブランチ（`feature/company-user-management`）と本変更のマージ順。本変更は同ブランチを起点にしているため、同ブランチのマージ後に PR を出すのが安全
