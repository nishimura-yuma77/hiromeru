# API設計（v0.1 ドラフト）

対象: hiromeru（AI支援型Xマーケティングシステム）MVP
根拠資料: `REQUIREMENTS.md`、`DATABASE.dbml`、`SCREEN_DESIGN.md`
機械可読な定義: `openapi.yaml`（OpenAPI 3.1。45パス・56オペレーション）

本書は `openapi.yaml` の読み物版であり、次の内容を扱う。OpenAPIに書きにくい設計判断（状態遷移、承認ゲート、非同期処理）、エージェントが呼ぶ内部ツールの定義、外部API（X / GA4 / OrcaRouter）との連携、画面との対応、未確定事項である。エンドポイントごとのスキーマ・エラー・例は `openapi.yaml` を正とする。両者が食い違う場合は `openapi.yaml` を優先し、本書を直す。

---

# 1. 設計方針

## 1.1 前提（ヒアリング結果と仮置き）

| 項目 | 内容 |
|------|------|
| API方式 | REST（JSON）。チャットの進捗のみ Server-Sent Events（SSE） |
| 認証 | 外部IdP（OIDC）でログインし、サーバー発行のセッションCookieで識別。IdPの選定は未確定（U-1） |
| 認可 | 会社単位のテナント分離。MVPは1ユーザー＝1会社＝1マーケターで、ロール別の出し分けはしない |
| 対象クライアント | 自社Webフロント（SC-00〜SC-10）と、cron等のスケジューラー（施策評価ジョブ） |
| 外部連携 | X API v2、GA4 Data API、OrcaRouter（LLM・埋め込み）。いずれもサーバー側からのみ呼ぶ |

## 1.2 設計原則

1. **承認はユーザーが直接APIを呼ぶことでのみ成立する。** エージェントのツールには、承認・投稿実行・削除実行の操作を含めない（NFR-SEC-003 / 004）。エージェントは「承認待ち」の状態を作るだけである。
2. **外部への副作用は冪等にする。** Xへの投稿には `Idempotency-Key` を必須とし、二重投稿を防ぐ（NFR-REL）。
3. **承認された内容と実行内容を一致させる。** 承認は `revision` と（承認カードでは）`payload_hash` に紐づける。承認後に内容が変わったら実行を拒否する。
4. **長い処理は待たせない。** チャットのターンと投稿は 202 Accepted で受け付け、進捗はSSEまたはポーリングで返す（NFR-PERF-001）。
5. **APIは生の値を返す。** 比率や円換算のような表示用の派生値は、原則としてクライアントが計算する（§12 U-14）。
6. **ログは追記専用で読み取りのみ公開する。** 実行履歴・セキュリティイベント・コストのAPIには更新・削除がない（NFR-OBS）。

## 1.3 共通規約

| 項目 | 規約 |
|------|------|
| ベースパス | `/api/v1` |
| 形式 | UTF-8のJSON。SSEのみ `text/event-stream` |
| 日時 | RFC 3339（UTC）。タイムゾーン変換はクライアント |
| ID | `int64` の整数 |
| セッション | Cookie `hiromeru_session`（HttpOnly / Secure / SameSite=Lax） |
| CSRF | `POST` / `PATCH` / `DELETE` は `X-CSRF-Token` を必須とする。値は `GET /me` で取得する |
| テナント分離 | 他社のリソースは存在しないものとして `404`（`403` にしない。存在の漏えいを防ぐ） |
| ページング | カーソル方式。`limit`（既定20、最大100）、`cursor`、レスポンスの `next_cursor`（末尾は `null`） |
| 楽観的排他 | 施策・投稿の更新／承認／投稿に `revision` を渡す。不一致は `409 REVISION_MISMATCH` |
| 冪等性 | 投稿実行と、Xへの投稿カードの承認に `Idempotency-Key` を必須とする。同じキーで異なる内容を送ると `409 IDEMPOTENCY_KEY_REUSED` |

## 1.4 エラー形式

RFC 9457（`application/problem+json`）。`type` / `title` / `status` / `detail` に加え、機械可読な `code` と、検証エラー時の `errors[]`（`pointer`、`message`）を返す。`detail` にはマスク済みの内容だけを入れる（NFR-SEC-005）。

| code | HTTP | 意味 |
|------|:----:|------|
| VALIDATION_ERROR | 400 | 入力の形式・範囲の誤り |
| UNAUTHENTICATED | 401 | セッションなし・期限切れ |
| FORBIDDEN | 403 | 権限なし（内部ジョブのトークン誤りなど） |
| CSRF_TOKEN_INVALID | 403 | `X-CSRF-Token` がない、または誤り |
| ACCOUNT_DISABLED | 403 | マーケターが無効化されている |
| NOT_FOUND | 404 | 存在しない、または他社のリソース |
| REVISION_MISMATCH | 409 | `revision` が最新と異なる（別の画面・エージェントが更新した） |
| INVALID_STATE | 409 | 現在のステータスでは実行できない操作 |
| APPROVAL_RESET_NOT_ACKNOWLEDGED | 409 | 承認済みの内容を編集する際、承認取消の確認がない |
| NOT_APPROVED_REVISION | 409 | 承認された改訂と現在の内容が一致しない |
| CAMPAIGN_HAS_POSTS | 409 | 投稿がある施策は削除できない（アーカイブのみ） |
| POST_PUBLISHED_UNDELETABLE | 409 | 投稿済みの投稿は削除できない |
| TURN_IN_PROGRESS | 409 | 同じセッションで別のターンが処理中 |
| APPROVAL_PAYLOAD_CHANGED | 409 | 承認カードの内容（`payload_hash`）が変わった |
| IDEMPOTENCY_KEY_REUSED | 409 | 同じ `Idempotency-Key` で内容が異なる |
| POST_BODY_TOO_LONG | 422 | Xの文字数規則を超える（UTM付きURLを含めて判定） |
| CAMPAIGN_NOT_APPROVED | 422 | 承認済みでない施策には投稿を作れない |
| LANDING_URL_REQUIRED | 422 | 遷移先URLが未入力 |
| INVALID_LANDING_URL | 422 | 遷移先URLが不正（スキーム・ホストの制限に違反） |
| RATE_LIMITED | 429 | 呼び出し過多。`Retry-After` を返す |
| UPSTREAM_ERROR | 502 | 外部API（X / GA4 / OrcaRouter）の障害。マスク済みの理由を返す |
| INTERNAL_ERROR | 500 | 想定外の障害 |

---

# 2. リソースとエンドポイント一覧

## 2.1 一覧

| タグ | メソッドとパス | operationId | 概要 |
|------|----------------|-------------|------|
| system | GET `/healthz` | getHealth | 死活確認（認証不要） |
| auth | GET `/auth/login` | startLogin | IdPへリダイレクト |
| | GET `/auth/callback` | finishLogin | IdPからの戻り。セッション発行 |
| | POST `/auth/logout` | logout | セッション破棄 |
| me | GET `/me` | getMe | ログインユーザー、CSRFトークン |
| | GET `/me/badges` | getNavBadges | ナビの承認待ち件数など |
| | GET `/config` | getClientConfig | 為替レート、文字数上限などの設定値 |
| campaigns | GET / POST `/campaigns` | listCampaigns / createCampaign | 一覧、手動作成 |
| | GET / PATCH / DELETE `/campaigns/{id}` | getCampaign / updateCampaign / deleteCampaign | 詳細、編集、削除 |
| | POST `/campaigns/{id}/submit` | submitCampaign | 承認申請 |
| | POST `/campaigns/{id}/approve` | approveCampaign | 承認 |
| | POST `/campaigns/{id}/reject` | rejectCampaign | 却下 |
| | POST `/campaigns/{id}/archive` | archiveCampaign | アーカイブ |
| | POST `/campaigns/{id}/restore` | restoreCampaign | 復元 |
| posts | GET / POST `/posts` | listPosts / createPost | 一覧、手動作成 |
| | GET / PATCH / DELETE `/posts/{id}` | getPost / updatePost / deletePost | 詳細、編集、削除 |
| | POST `/posts/{id}/submit` | submitPost | 承認申請 |
| | POST `/posts/{id}/approve` | approvePost | 承認 |
| | POST `/posts/{id}/publish` | publishPost | Xへ投稿（非同期） |
| | POST `/posts/{id}/archive` | archivePost | アーカイブ |
| | POST `/posts/{id}/restore` | restorePost | 復元 |
| | POST `/posts/{id}/tracking-link/preview` | previewTrackingLink | UTM付きURLのプレビュー |
| metrics | GET `/metrics` | getMetricsReport | 計測結果の集計（SC-06） |
| | GET `/posts/{id}/metric` | getPostMetric | 投稿1件の計測状態と失敗履歴 |
| memories | GET / POST `/memories` | listMemories / createMemory | 一覧・意味検索、手動登録 |
| | GET / DELETE `/memories/{id}` | getMemory / deleteMemory | 詳細、忘却（PATCHなし） |
| chat | GET / POST `/chat/sessions` | listChatSessions / createChatSession | 会話一覧、新規 |
| | GET / PATCH `/chat/sessions/{id}` | getChatSession / updateChatSession | 詳細、アーカイブ |
| | GET / POST `/chat/sessions/{id}/turns` | listChatTurns / createChatTurn | 履歴、発話（202） |
| | GET `/chat/turns/{id}` | getChatTurn | ターンの状態 |
| | GET `/chat/turns/{id}/events` | streamChatTurn | SSEで進捗を購読 |
| | POST `/chat/turns/{id}/cancel` | cancelChatTurn | 停止 |
| | POST `/chat/turns/{id}/retry` | retryChatTurn | 失敗したターンの再試行 |
| | GET `/chat/approvals` | listPendingApprovals | 承認待ちカードの一覧 |
| | POST `/chat/tool-executions/{id}/approve` | approveToolExecution | 承認カードを承認 |
| | POST `/chat/tool-executions/{id}/reject` | rejectToolExecution | 承認カードを却下（修正指示つき） |
| ops-cost | GET `/ops/cost/summary` | getCostSummary | コスト集計（SC-08） |
| | GET `/ops/cost/llm-calls` | listLlmCalls | LLM呼び出し一覧 |
| ops-sessions | GET `/ops/sessions` | listOpsSessions | 実行履歴の一覧（SC-09） |
| | GET `/ops/sessions/{id}` | getOpsSession | セッションのヘッダー |
| | GET `/ops/sessions/{id}/turns` | listOpsTurns | ターン一覧 |
| | GET `/ops/turns/{id}` | getOpsTurn | アイテム・ツール実行・LLM呼び出し・検出イベント |
| ops-security | GET `/ops/security/events` | listSecurityEvents | セキュリティイベント一覧（SC-10） |
| | GET `/ops/security/events/{id}` | getSecurityEvent | 詳細 |
| internal | POST `/internal/jobs/metrics-collection` | runMetricsCollection | 施策評価ジョブ（cron） |

## 2.2 設計上のポイント

- 施策・投稿の**新規作成の主経路はチャット（エージェント）**であり、`POST /campaigns`・`POST /posts` は手動作成用である。手動作成は `draft` で保存される。
- 記憶は**編集できない**（PATCHなし）。内容と埋め込みベクトルの整合を保つため、変更は「忘却して登録し直す」とする。忘却は内容とベクトルの完全削除である（確認ダイアログ必須）。
- `GET /memories` は `q` を渡すと意味検索になる（埋め込みAPIを1回呼ぶためコスト対象）。`q` なしは一覧のみで、LLM・埋め込みは呼ばない。
- 一覧APIは、画面が「今できる操作」を出し分けられるよう、サーバーが状態から算出した `allowed_actions`（施策: `edit` / `submit` / `approve` / `reject` / `archive` / `restore` / `delete` / `create_post`。投稿はさらに `publish` / `republish` / `open_on_x` / `view_metrics`）を返す。UIの出し分けロジックをクライアントに複製しない。

---

# 3. 認証・セッション

## 3.1 ログインフロー

1. クライアントが `GET /auth/login?return_to=...` に遷移する。サーバーは `state` と PKCE の `code_verifier` を保存し、IdPの認可エンドポイントへ302で送る。
2. IdPが `GET /auth/callback?code=...&state=...` へ戻す。サーバーは `state` を検証し、トークンを交換し、IDトークンからユーザーを特定する。
3. 初回ログインなら、ユーザー・会社・マーケターを**自動作成**する（仮置き。U-1）。既存ユーザーで、マーケターが無効なら `ACCOUNT_DISABLED`。
4. セッションCookieを発行し、`return_to`（同一オリジンのパスのみ許可）へ302する。
5. クライアントは `GET /me` でユーザー情報と `csrf_token` を取得し、以後の変更系リクエストの `X-CSRF-Token` に付ける。

## 3.2 セッションの扱い

- セッションには有効期限（アイドル・絶対の2種）を設ける。期限切れは `401 UNAUTHENTICATED` を返し、クライアントはログイン画面へ遷移する。
- ログアウトはサーバー側でセッションを失効させる。Cookieの削除だけでは終わらせない。
- 外部APIのトークン（X・GA4）はブラウザに渡さない。サーバー側の設定として保持する（MVPは単一アカウント。U-12）。

## 3.3 内部ジョブの認証

`/internal/*` はユーザーセッションを使わず、`Authorization: Bearer <internalToken>` で認証する（共有シークレット、またはプラットフォームのサービス認証）。トークンが誤っていれば `403 FORBIDDEN`。ブラウザ向けのCORS許可は行わない。

---

# 4. 施策・投稿のライフサイクル

## 4.1 施策のステータス遷移

| 現在 | 操作 | 遷移先 | 備考 |
|------|------|--------|------|
| （なし） | 承認カードの承認（チャット） | approved | `revision = approved_revision = 1` で保存 |
| （なし） | `POST /campaigns`（手動） | draft | |
| draft | submit | pending_approval | |
| pending_approval | approve | approved | `approved_revision = revision` |
| pending_approval | reject | rejected | |
| pending_approval | 編集 | pending_approval | `revision + 1` |
| approved | 編集（要 `acknowledge_approval_reset: true`） | pending_approval | `revision + 1`。**仮置き**（U-10）。承認が取り消される |
| rejected | 編集して submit | pending_approval | |
| draft / rejected / approved | archive | archived | |
| archived | restore | draft | **仮置き**（U-12）。復元すると承認は失われる |
| draft | delete | （削除） | 投稿が1件でもあれば `CAMPAIGN_HAS_POSTS` |

- 施策の承認が配下の投稿に及ぼす影響はない（U-11）。投稿は自身の承認済み改訂で判断する。
- 承認済みの施策を編集する際、`acknowledge_approval_reset` が `true` でなければ `409 APPROVAL_RESET_NOT_ACKNOWLEDGED` を返す（SC-03の確認ダイアログに対応）。

## 4.2 投稿のステータス遷移と投稿フロー

| 現在 | 操作 | 遷移先 | 備考 |
|------|------|--------|------|
| （なし） | 承認カードの承認（チャット） | approved | 同時に `post_tracking_links` を生成 |
| （なし） | `POST /posts`（手動） | draft | 承認済みの施策のみ指定可（U-4） |
| draft | submit | pending_approval | |
| pending_approval | approve | approved | `approved_revision = revision` |
| pending_approval / approved | 編集 | pending_approval | `revision + 1`。承認済みは要 `acknowledge_approval_reset`（U-10） |
| approved / publish_failed | publish | publishing | 202。要 `Idempotency-Key`、要 `revision` |
| publishing | （X APIの結果） | published | X投稿ID・投稿日時を保存。計測予定日は公開から7日後 |
| publishing | （X APIの失敗） | publish_failed | マスク済みエラーを保存 |
| publish_failed | 編集 | pending_approval | 本文が変わるため再承認 |
| draft / approved / publish_failed / published | archive | archived | |
| archived | restore | draft | **仮置き**（U-12） |
| draft | delete | （削除） | `published` は `POST_PUBLISHED_UNDELETABLE` |

### 投稿の実行（`POST /posts/{id}/publish`）

リクエスト: `revision`（画面が表示していた改訂）と、ヘッダー `Idempotency-Key`。

サーバーの処理順序:

1. セッション・CSRF・テナントを確認する。
2. `Idempotency-Key` を検索する。同じキー・同じ内容の完了済みリクエストがあれば、その結果を再返却する（X APIは再度呼ばない）。内容が異なれば `409 IDEMPOTENCY_KEY_REUSED`。
3. 投稿を条件付きで `approved` / `publish_failed` → `publishing` へ**原子的に**遷移させる。すでに `publishing` なら `409 INVALID_STATE`（二重押しの防止）。
4. `revision == approved_revision` を確認する。不一致なら `409 NOT_APPROVED_REVISION`（承認後に内容が変わっている）。
5. 投稿テキストを組み立てる（下記）。Xの文字数規則を超える場合は `POST_BODY_TOO_LONG`（この時点で `publishing` に遷移させない）。
6. `202 Accepted` を返す。本体の処理（X APIの呼び出し）は非同期で続行する。
7. X API `POST /2/tweets` を呼ぶ。成功したら `published`、失敗したら `publish_failed` にする。

クライアントは数秒間隔で `GET /posts/{id}` をポーリングし、`status` が `publishing` でなくなったら結果を表示する。

**結果不明の扱い**: X APIがタイムアウトした場合、投稿が実際には成功している可能性がある。この場合は自動で再送せず `publish_failed` とし、エラー詳細に「結果不明（Xで投稿が公開されていないか確認してください）」と明記する。再投稿はユーザーが確認したうえで行う（二重投稿を避けるため）。

**投稿テキスト**: `本文 + 改行 + UTM付きURL`（仮置き。U-13）。本文にすでに遷移先URLが含まれる場合の扱いは要判断。

## 4.3 UTMリンクの生成規則

UTMは**決定論的に**生成し、LLMは使わない（NFR-COST）。

| パラメータ | 値 |
|-----------|----|
| `utm_source` | `x` |
| `utm_medium` | `social` |
| `utm_campaign` | `c{campaign_id}` |
| `utm_content` | `p{post_id}` |

- 遷移先URL（`landing_url`）は投稿ごとに入力する（U-9）。`http(s)` のみ許可し、既存のクエリは保持する。すでにUTMが付いていれば上書きする。
- 生成したURLは `post_tracking_links` に保存し、承認カード・SC-05の確認ダイアログには保存前に `POST /posts/{id}/tracking-link/preview` の結果を表示する。
- GA4での集計はこの値（`sessionSource` / `sessionMedium` / `sessionCampaignName` / `sessionManualAdContent`）と一致させる（§7.2）。

---

# 5. チャット（SC-01）と承認カード

## 5.1 ターンの流れ

1. クライアントが `POST /chat/sessions` でセッションを作る（または既存を使う）。
2. `POST /chat/sessions/{id}/turns` に発話（`content`、任意で `campaign_id` などの文脈）を送る。サーバーはユーザー入力を検査（プロンプトインジェクション・機密情報）し、`202 Accepted` とターンを返す。同一セッションで処理中のターンがあれば `409 TURN_IN_PROGRESS`。
3. クライアントは `GET /chat/turns/{id}/events` をSSEで購読し、進捗を画面に反映する。
4. ターンは `pending → running → completed / failed / cancelled / blocked` と遷移する。

## 5.2 SSEイベント

| event | 内容 |
|-------|------|
| turn.started | ターン開始 |
| message.delta | アシスタント発話の増分 |
| item.created | アイテム（発話・ツール呼び出し・ツール結果）の確定 |
| tool_execution.updated | ツール実行の状態変化（running / waiting_for_approval / completed / failed / blocked） |
| approval.requested | 承認カードが作られた（カードの内容を含む） |
| item.context_status_changed | アイテムが隔離された（内容は送らず、状態のみ） |
| usage.updated | 累積のトークン数とコスト（上限判定の根拠） |
| turn.completed / turn.failed / turn.cancelled / turn.blocked | ターンの終了 |

- 各イベントには単調増加の `id` を付ける。切断後は `Last-Event-ID` ヘッダーで再開できる。
- 30秒ごとに `ping` コメントを送り、プロキシによる切断を防ぐ。
- 承認待ちのターンは `running` のまま `waiting_for_approval: true` を持つ（U-15）。SSEは接続を保つが、承認待ちが長時間になる場合、クライアントは切断して `GET /chat/approvals` で復元してよい。
- 隔離されたアイテム（プロンプトインジェクション等）の元の内容は、チャットAPIでは**返さない**。表示は省略され、運用APIの `getOpsTurn` が代替内容（`context_override`）と隔離理由だけを返す。

## 5.3 承認カード

承認カードは `status = waiting_for_approval` のツール実行である。

| kind | 元のツール | カードの内容 | 承認時の結果 |
|------|-----------|--------------|--------------|
| campaign_commit | `submit_campaign_proposal`（campaign_planner）／`save_campaign`（親） | 施策案の全項目 | 施策を `approved`（`revision = approved_revision = 1`）で保存 |
| post_content_commit | `submit_post_draft`（content_creator）／`save_post`（親） | 本文・URL・対象施策 | 投稿を `approved` で保存、`post_tracking_links` を生成 |
| x_publish | `publish_post`（親） | 最終本文、UTM付きURL | §4.2の投稿実行と同じ処理（202・非同期） |
| data_delete | `delete_*`（親） | 削除対象と影響範囲 | 該当データを削除（記憶は内容とベクトルを完全削除） |

**承認 API（`POST /chat/tool-executions/{id}/approve`）**

- リクエストに、画面が表示していたカードの `payload_hash` を必ず含める。サーバー側のカードの内容と一致しなければ `409 APPROVAL_PAYLOAD_CHANGED`（表示と承認の内容を一致させる）。
- `x_publish` の承認には `Idempotency-Key` が必須である。
- すでに承認・却下・失効している場合は `409 INVALID_STATE`。同じ承認の再送は、結果が同じなら冪等に扱う。
- 承認後、ツール実行は `running → completed` になる。**承認処理を行うのはこのAPIのサーバーコードであり、エージェント（LLM）ではない。** 実行結果はツール結果アイテムとして会話に追記され、承認前にサスペンドされていたターンは再開して終了する。

**却下 API（`POST /chat/tool-executions/{id}/reject`）**

- `instruction`（修正指示）を任意で受け取る。指示があれば、それを入力とする新しいターンを開始する（SC-01の「修正を依頼」）。
- 却下したツール実行は `cancelled` になる。施策の承認カードを却下しても `rejected` の施策行は作らない（U-2の仮置き）。

## 5.4 ターンの上限と停止

- ステップ数・コストの上限（アプリケーション設定）に達したターンは `failed` で終了し、`error_code` を `STEP_LIMIT` または `COST_LIMIT` にする。UIは専用文言を表示する。
- `POST /chat/turns/{id}/cancel` で実行中のターンを停止できる（`cancelled`）。実行中のLLM呼び出しは中断し、外部への副作用のあるツール（投稿実行）はキャンセルできない。
- `POST /chat/turns/{id}/retry` は `failed` のターンだけを対象とし、同じ入力で新しいターンを作る。

---

# 6. エージェントのツール定義（内部インターフェース）

外部に公開するHTTP APIではなく、エージェント基盤がLLMのツール呼び出しとして提供する関数の定義である。**承認・投稿実行・削除実行は、どのエージェントのツールにも含めない**（NFR-SEC-004）。

## 6.1 権限マトリクス

| ツール | 親 | campaign_planner | content_creator | 承認 | 概要 |
|--------|:--:|:----------------:|:---------------:|:----:|------|
| ask_user | ○ | ○ | ○ | - | ユーザーへの質問（ターンを一時停止） |
| search_memories | ○ | ○ | ○ | - | 記憶の意味検索（読み取り） |
| get_campaign / list_campaigns | ○ | ○ | ○ | - | 施策の参照 |
| get_post / list_posts | ○ | ○ | ○ | - | 投稿の参照 |
| get_metrics | ○ | ○ | ○ | - | 計測結果の参照 |
| web_search | ○ | ○ | ○ | - | Web検索 |
| web_fetch | ○ | ○ | ○ | - | URL取得（URL制限あり） |
| save_memory | ○ | - | - | - | 記憶の保存（ユーザー指定・評価結果） |
| call_campaign_planner | ○ | - | - | - | 施策立案エージェントの呼び出し |
| call_content_creator | ○ | - | - | - | コンテンツ制作エージェントの呼び出し |
| save_campaign | ○ | - | - | **要** | 施策の保存（campaign_commit） |
| submit_campaign_proposal | - | ○ | - | **要** | 施策案の提出（campaign_commit） |
| save_post | ○ | - | - | **要** | 投稿の保存（post_content_commit） |
| submit_post_draft | - | - | ○ | **要** | 投稿案の提出（post_content_commit） |
| publish_post | ○ | - | - | **要** | 投稿の依頼（x_publish の承認待ちを作る） |
| delete_campaign / delete_post / delete_memory | ○ | - | - | **要** | 削除の依頼（data_delete の承認待ちを作る） |

- 「承認：要」のツールは、**実行せずに承認待ちの状態を作る**だけである。実際の保存・投稿・削除は、ユーザーが承認APIを呼んだ後にサーバーが行う。
- `content_creator` は `publish_post`・`delete_*`・`save_campaign` を持たない。`campaign_planner` は投稿系の書き込みを持たない。サブエージェントは親の権限を拡張できない。
- サブエージェントの呼び出し結果は、親のツール結果として返る。サブエージェントのセッションは `parent_session_id` で親と結び付く。

## 6.2 ツール結果の共通形式

```json
{
  "status": "ok",
  "data": { },
  "error": null
}
```

失敗時:

```json
{
  "status": "error",
  "data": null,
  "error": {
    "code": "UPSTREAM_ERROR",
    "message": "（マスク済みの理由）",
    "retryable": true
  }
}
```

- エージェントは、失敗を成功として扱ってはならない。失敗した場合は、その旨をユーザーに伝える（SCREEN_DESIGN 6.1）。
- 承認待ちを作ったツールの結果は `status: "waiting_for_approval"` とし、`tool_execution_id` を返す。

## 6.3 主要ツールの入出力

| ツール | 主な入力 | 主な出力 |
|--------|----------|----------|
| ask_user | `question`, `choices?` | ユーザーの回答（ターンを再開したときに得る） |
| search_memories | `query`, `limit?` | 記憶の配列（`id`, `content`, `related_campaign_id?`, `score`） |
| get_campaign | `id` | 施策（承認状態と `revision` を含む） |
| list_campaigns | `status?`, `limit?` | 施策の要約の配列 |
| get_post / list_posts | `id` / `campaign_id?`, `status?` | 投稿（本文・状態・UTMリンク） |
| get_metrics | `campaign_id?`, `post_id?`, `from?`, `to?` | 生のPV数・流入ユーザー数（比率は返さない。U-14） |
| web_search | `query`, `limit?` | 検索結果（タイトル・URL・抜粋）。**非信頼データ**として包む |
| web_fetch | `url` | 本文の要約または抜粋。**非信頼データ**として包む |
| save_memory | `content`, `campaign_id?`, `post_id?` | `memory_id` |
| call_campaign_planner | `brief`（目的・ターゲットなど） | サブエージェントの最終発話と承認待ちの施策案（あれば） |
| call_content_creator | `campaign_id`, `brief` | サブエージェントの最終発話と承認待ちの投稿案（あれば） |
| save_campaign / submit_campaign_proposal | 施策の全項目 | `tool_execution_id`（承認待ち） |
| save_post / submit_post_draft | `campaign_id`, `body`, `landing_url` | `tool_execution_id`（承認待ち） |
| publish_post | `post_id`, `revision` | `tool_execution_id`（承認待ち） |
| delete_* | 対象の `id` | `tool_execution_id`（承認待ち） |

## 6.4 非信頼データの扱い（NFR-SEC-001 / 002）

- Web検索・URL取得の結果、外部から取り込んだテキストは、`{"untrusted": true, "source": "web", "content": ...}` の形で包み、**指示として解釈しない**旨をシステムプロンプトで明示する。
- `web_fetch` には次の制限を設ける: `http` / `https` のみ、プライベートIP・リンクローカル・メタデータエンドポイント・`localhost` は拒否（SSRF対策）、リダイレクトは各ホップで再検証、応答サイズ・時間の上限、Content-Typeの制限。
- ツールに渡す引数はスキーマで検証する。検証に失敗した呼び出しは実行せず、`unauthorized_tool_call` としてセキュリティイベントに記録する。
- 検査で検出された入力・出力は、`SecurityEvent` に記録し（§8）、隔離したアイテムの代わりに固定の代替内容を LLM に渡す。

---

# 7. 外部API連携

## 7.1 X API v2

| 用途 | 呼び出し | 備考 |
|------|----------|------|
| 投稿 | `POST /2/tweets`（`text`） | レスポンスの `data.id` をX投稿IDとして保存する |
| 初週PV数の取得 | `GET /2/tweets?ids=...&tweet.fields=public_metrics`（`impression_count`） | 投稿から7日後に取得する |

- 認証は OAuth 2.0 のユーザーコンテキスト（スコープ `tweet.write`、`tweet.read`、`users.read`、`offline.access`）。MVPは単一アカウントのトークンをサーバー側で保持し、更新はサーバーが行う（U-12）。
- 利用しているXのプランとレート制限は未確認である。投稿数とインプレッション取得の可否がプランで変わるため、実装前に確認する。
- 429・5xx・タイムアウトは再試行可能、4xx（認可・重複・文字数超過）は再試行しない。
- 認可情報（トークン）はログ・履歴に残さない。エラーの内容は保存前にマスクする（NFR-SEC-005）。

## 7.2 GA4 Data API

| 用途 | 呼び出し |
|------|----------|
| 投稿経由の応募ページ流入ユーザー数 | `POST https://analyticsdata.googleapis.com/v1beta/properties/{propertyId}:runReport` |

- スコープは `analytics.readonly`。
- 次のディメンションでフィルタし、投稿の `utm_*` と突き合わせる: `sessionSource`（=`x`）、`sessionMedium`（=`social`）、`sessionCampaignName`（=`c{campaign_id}`）、`sessionManualAdContent`（=`p{post_id}`）。
- 指標は `activeUsers`（または `totalUsers`）。どちらを「流入ユーザー数」とするかは仮置き。
- 日付範囲は、公開日から7日間（公開日を含める）。GA4は日単位の粒度であり、公開時刻の時分は考慮できない。
- GA4のデータは反映に遅延がある（通常24〜48時間）。投稿から7日後の取得時点で、最終日のデータが未確定の可能性がある。

## 7.3 OrcaRouter（LLM・埋め込み）

| 項目 | 内容 |
|------|------|
| LLM呼び出し | ヘッダー `X-OrcaRouter-Include-Cost: true` を付け、レスポンスの `usage.cost_usd` を `llm_calls.cost_usd` に保存する |
| 請求の確定値 | レスポンスヘッダー `X-Orca-Request-Id` を `llm_calls.orcarouter_request_id` に保存する。`GET /v1/generation?id=` で確定したコストを取得できる（後追い補正用） |
| 使用量 | `usage.prompt_tokens` / `completion_tokens` を保存する |
| 検査 | Guardrails（機密情報・プロンプトインジェクション）とFirewall。検出結果は `security_events` に `detector = orcarouter_guardrail / orcarouter_firewall` として記録する |
| モデル | 設定した単一のモデルと埋め込みモデルを使う。モデル名を `llm_calls` に持たないため、モデル別の集計はできない（U-5） |

- コストが取得できない呼び出しは `cost_usd = NULL` で保存し、SC-08は「コスト不明の呼び出し件数」として別に表示する（合計に含めない）。
- 埋め込みAPIの呼び出し（記憶の保存・意味検索）もコストの記録対象である。

---

# 8. 運用系API（SC-08〜SC-10）

| 画面 | API | ポイント |
|------|-----|----------|
| SC-08 コスト | `getCostSummary`, `listLlmCalls` | 合計は `cost_usd` の合計（`NULL` 除外）。日別はクエリの `tz`（既定 `Asia/Tokyo`）の暦日で区切る。円換算はクライアントが `GET /config` の `jpy_per_usd` で行う（U-8）。エージェント別は `llm_calls → agent_turns → agent_sessions.agent` で集計する |
| SC-09 実行履歴 | `listOpsSessions`, `getOpsSession`, `listOpsTurns`, `getOpsTurn` | 読み取り専用。「どのエージェントの、どの処理で、何が失敗したか」を辿れる。アイテム内容は保存時にマスク済み。生の推論内容は保存しないため返せない |
| SC-10 セキュリティ | `listSecurityEvents`, `getSecurityEvent` | 追記専用。検出のみ記録され、成功した検査は記録されない。よって0件は「問題が検出されていない」を意味する。`enforcement`: `observed`（検知のみ）/ `sanitized`（無害化）/ `blocked`（遮断） |

---

# 9. 計測（SC-06）と施策評価ジョブ

## 9.1 計測結果の取得

- `GET /metrics` は、投稿日時（`from` / `to`）・施策（`campaign_id`）・計測ステータス（`metric_status`）で絞り込み、**施策ごとにグループ化**した結果を返す。各グループは、施策の要約（`campaign`）、計測完了分の合計（`totals`: `measured_post_count` / `x_pv_total` / `landing_user_total`）、投稿ごとの行（`posts`）を持つ。時系列や全体KPIは返さず、必要ならクライアントがグループから集計する。
- **APIは生の値だけを返す**: X投稿の初週PV数（`x_pv_count`）と、投稿経由の応募ページ流入ユーザー数（`landing_user_count`）。流入率などの比率・平均は返さない。SC-06のグラフ・表の比率は、クライアントが「流入ユーザー数 ÷ PV数」として算出する（U-14）。
- 分母（PV数）が0の投稿の比率は「−」と表示する（0%としない）。計測未完了（`pending` / `processing` / `failed`）の投稿は、集計に含めず、件数だけを別に返す。
- `GET /posts/{id}/metric` は計測の状態と、`post_metric_failures`（発生元 `x` / `ga4`、再試行可否、マスク済みエラー）を返す。

## 9.2 ジョブの実行（`POST /internal/jobs/metrics-collection`）

cronが定期的（例: 毎時）に呼ぶ。対象は、`post_metrics.status` が `pending`、または `failed` かつ再試行可能で上限未満で、`scheduled_at <= as_of` の投稿である。

各投稿の処理:

1. `pending` / `failed` → `processing` へ**条件付きで原子的に**遷移させる（`UPDATE ... WHERE status IN (...)` の影響行数が1のワーカーだけが処理する）。
2. X APIから初週PV数、GA4から流入ユーザー数を取得する。
3. 両方成功したら `completed`（両方の値と `measured_at`）にする。
4. どちらかが失敗したら、`post_metric_failures` に発生元・再試行可否・マスク済みエラーを追記し、`failed` にする。
5. 完了時に、評価結果を要約した記憶を保存し、施策・投稿に紐づける。**決定論的なテンプレートで生成し、LLMは呼ばない**（NFR-COST-005）。埋め込みは1回だけ呼ぶ。

再試行:

- 再試行可能なエラー（HTTP 429 / 5xx / タイムアウト）は、`post_metric_failures` の件数が上限（アプリケーション設定）に達するまで再試行する。恒久的なエラーは再試行しない。
- 再試行上限に到達した投稿は、手動の再計測ボタンを置かない方針のため（U-6）、SC-06で「計測失敗（要調査）」として残る。

冪等性: `post_metrics` は投稿IDが主キーのため、ジョブを複数回実行しても評価データは重複しない。一部の投稿の失敗はジョブ全体を失敗させず、`200` で `targeted` / `completed` / `failed` / `skipped` の件数を返す。`dry_run: true` は対象の抽出だけを行う。

---

# 10. 画面とAPIの対応

| 画面 | 主に呼ぶAPI |
|------|-------------|
| SC-00 ログイン | `startLogin` → `finishLogin` → `getMe`（`csrf_token` 取得）、`logout` |
| 共通レイアウト | `getMe`, `getNavBadges`（承認待ち件数など。定期更新）, `getClientConfig` |
| SC-01 ホーム | `listChatSessions`, `createChatSession`, `listChatTurns`, `createChatTurn`, `streamChatTurn`, `cancelChatTurn`, `retryChatTurn`, `listPendingApprovals`, `approveToolExecution`, `rejectToolExecution` |
| SC-02 施策一覧 | `listCampaigns`, `createCampaign` |
| SC-03 施策詳細 | `getCampaign`, `updateCampaign`, `submitCampaign`, `approveCampaign`, `rejectCampaign`, `archiveCampaign`, `restoreCampaign`, `deleteCampaign`（「この施策で投稿案を作る」はSC-01へ遷移し、`createChatTurn` に `campaign_id` を文脈として渡す） |
| SC-04 投稿一覧 | `listPosts`, `createPost` |
| SC-05 投稿詳細 | `getPost`（投稿中のポーリング）, `updatePost`, `submitPost`, `approvePost`, `previewTrackingLink`, `publishPost`, `archivePost`, `restorePost`, `deletePost`, `getPostMetric` |
| SC-06 計測結果 | `getMetricsReport`, `getPostMetric` |
| SC-07 記憶 | `listMemories`（`q` で意味検索）, `getMemory`, `createMemory`, `deleteMemory` |
| SC-08 コスト | `getCostSummary`, `listLlmCalls`, `getClientConfig`（為替レート） |
| SC-09 実行履歴 | `listOpsSessions`, `getOpsSession`, `listOpsTurns`, `getOpsTurn` |
| SC-10 セキュリティ | `listSecurityEvents`, `getSecurityEvent` |

---

# 11. 非機能要件との対応（抜粋）

| 要件 | 対応する設計 |
|------|--------------|
| NFR-SEC-001 / 002（非信頼データ・SSRF） | §6.4 非信頼データの包み込み、`web_fetch` のURL制限 |
| NFR-SEC-003 / 004（人間の承認・最小権限） | §1.2 原則1、§5.3 承認カード、§6.1 権限マトリクス |
| NFR-SEC-005（機密のマスク） | エラー・履歴・ログはマスク済みの内容のみ。外部APIの認可情報は保存しない |
| NFR-REL（二重実行防止・障害時の継続） | `Idempotency-Key`、`publishing` への条件付き遷移、ジョブの原子的な遷移、結果不明時の非再送 |
| NFR-REL-006（承認待ちの復元） | `GET /chat/approvals`、SSEの `Last-Event-ID` |
| NFR-REL-007（ジョブの多重実行） | §9.2 条件付き遷移と投稿IDの主キー |
| NFR-PERF-001（待たせない） | 202 Accepted、SSE、投稿のポーリング |
| NFR-COST（コスト管理） | `usage.updated`、`STEP_LIMIT` / `COST_LIMIT`、UTM・評価要約をLLMなしで生成 |
| NFR-OBS-001〜003（追跡・コスト・モデル） | §8 運用系API（モデル別はU-5で保留） |

---

# 12. 未確定事項・要判断事項

`SCREEN_DESIGN.md` §7 の未確定事項（U-1〜U-11）のうち、API設計に影響するものと、本書で新たに生じたものを示す。

## 12.1 既存の未確定事項（API上の仮置き）

| # | 内容 | API上の仮置き |
|---|------|---------------|
| U-1 | 初回ログイン時のユーザー・会社・マーケターの作成方法とIdP | 初回ログインで自動作成。IdPは未定（OIDCの汎用実装） |
| U-2 | 施策の未承認案の置き場所 | チャットの提案は履歴のみ。`rejected` の施策行は手動作成・SC-03経由でのみ作る |
| U-4 | 手動での投稿作成の可否・対象施策の条件 | 承認済みの施策のみ指定可（`CAMPAIGN_NOT_APPROVED`） |
| U-5 | 使用モデルの記録先 | モデル別集計のAPIは返さない。`llm_calls.model` 追加、またはOrcaRouterの照会を要判断 |
| U-6 | 計測失敗時の手動再計測 | APIを置かない。上限到達後の扱いを要判断 |
| U-7 | 記憶の作成日時・種別 | 作成日時・種別は返さず、日付順の並び替えや種別フィルタも提供しない。DBに追加した後にフィルタを足す |
| U-8 | 円換算の為替レートの出所 | 固定値を `GET /config` の `jpy_per_usd` で返す |
| U-9 | 遷移先URLの入力主体 | 投稿ごとに入力（`landing_url`）。会社共通の設定にするか要判断 |
| U-10 | 承認済み投稿・施策を編集した際の戻り先 | `pending_approval`。`acknowledge_approval_reset: true` を必須にする |
| U-11 | 施策の承認が投稿に及ぼす影響 | 影響なし |

## 12.2 本書で新たに生じた未確定事項

| # | 内容 | 仮置き・論点 |
|---|------|--------------|
| U-12 | ①アーカイブからの復元先。②X・GA4の認可を単一アカウントのサーバー設定とする点 | ①`draft` に戻し、承認は失われる（`approved` に戻すと、承認時の内容との同一性が保証できないため）。②MVPは単一アカウント。複数アカウント対応は範囲外 |
| U-13 | 投稿テキストの組み立て | 本文＋改行＋UTM付きURL。本文にURLが含まれる場合の重複・置換の扱いは未確定 |
| U-14 | 生の値だけを返す方針と、SC-06のグラフ画面が表示する「流入率」との関係。SCREEN_DESIGN の設計原則6（比率を出さない）とグラフ画面の実装が食い違っている | APIは生の値のみ返し、比率はクライアントが計算する。原則6を「単一の比率だけで優劣を示さない」等に改めるか、グラフ画面から比率を外すかを要判断 |
| U-15 | 承認待ちのターンの状態。SCREEN_DESIGN は「ターン終了後も承認カードが残る」と書くが、DBに承認待ちを表すターン状態がない | ターンは `running` のまま `waiting_for_approval: true` を持つ。承認待ちを表す状態（例: `waiting_for_approval`）をDBに追加するか、承認待ちのターンを `completed` で終わらせ、承認を別ターンで再開するかを要判断 |

## 12.3 実装前に確認する外部仕様

- Xの利用プラン、投稿数・インプレッション取得のレート制限。
- GA4の指標（`activeUsers` と `totalUsers` のどちらを使うか）と、データ反映の遅延を考慮した取得タイミング。
- OrcaRouterの Guardrails / Firewall のレスポンス形式（検出結果を `security_events` にどう対応付けるか）。
- IdP（OIDC）の選定。
