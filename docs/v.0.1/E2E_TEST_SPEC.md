# E2Eテスト仕様書

## 1. 目的

本書は、Hiromeru v0.1の主要なユーザー操作フローを、Frontend、Backend、PostgreSQLを横断して確認するE2Eテストの仕様を定義する。

テストは正常系の業務フローを優先し、異常系は、二重実行や外部公開など利用者または業務データへの影響が大きいものに限定する。各テストケースは、具体的な操作と、その操作に対応する確認項目、関連画面、関連APIを必須とする。

## 2. 対象範囲

### 2.1 対象

- `SCREEN_DESIGN.md`のSC-01、SC-02、SC-04からSC-09
- ログインから施策作成、X投稿公開、計測、長期記憶の利用までのユーザーフロー
- BrowserからNext.js、FastAPI、PostgreSQLまでの接続
- Agent Turn、承認API、参照API、Cronによる状態変化
- 認証Cookie、CSRF、会社・マーケターのデータ境界
- X、GA4、LLM、EmbeddingのFakeを含む外部連携境界

### 2.2 対象外

- Component、関数、Repository単位の単体テスト
- APIごとの入力境界値を網羅するテスト
- ブラウザやOSの全組み合わせを対象とする互換性テスト
- 負荷、長時間稼働、侵入、脆弱性診断
- Vercel WAFによるログイン回数制限そのものの動作
- 実際のX、GA4、OrcaRouterへの接続
- `SCREEN_DESIGN.md`で`/chat`への遷移が定義されている`/`と、現行実装のLanding Page

## 3. 参照文書

| 文書 | 本書で参照する内容 |
| --- | --- |
| `REQUIREMENTS.md` | MVPの基本フロー、非機能要件 |
| `USECASE.md` | 施策作成・更新、X投稿作成・公開のユーザー起点フロー |
| `SCREEN_DESIGN.md` | 画面、URL、表示、画面遷移、ユーザー操作 |
| `API_DESIGN.md` | API、Request、Response、認証、CSRF、冪等性、エラー |
| `AGENT_DESIGN.md` | Agent、Tool、Turn、進捗、中断復旧 |
| `CRON.md` | 投稿指標取得、評価記憶生成、再試行 |
| `DATABASE.dbml` | 保存データ、関連、制約 |

仕様が食い違う場合は、各参照文書が定める正本の優先順位に従う。

## 4. テスト方針

### 4.1 E2Eの境界

- ユーザー操作はBrowserから行い、画面が呼び出す実際のAPIを使用する
- Frontend、Backend、PostgreSQLは実際のアプリケーションを使用する
- X、GA4、LLM、Embedding、Web検索・取得は決定論的なFakeへ差し替える
- テストから業務APIを直接呼び出して主操作を省略しない
- API直接呼び出しとDB直接操作は、事前条件の準備、外部障害の注入、事後結果の確認だけに使用する
- 各ケースは独立して実行でき、別ケースの実行結果へ依存しない
- 時刻、UUID、Fakeの応答は固定し、同じ入力に対して同じ結果を再現する

### 4.2 確認レベル

各ケースでは、必要に応じて次の3段階を確認する。

| レベル | 確認内容 |
| --- | --- |
| UI | 表示、入力値、画面遷移、操作可否、利用者向け通知 |
| API | Method、Path、Status、主要なRequest・Response、呼び出し回数 |
| 永続化・外部作用 | DBの作成・更新件数、関連、Fake外部APIの呼び出し内容と回数 |

### 4.3 正常系と異常系

- 正常系は、利用者が目的を達成する一連のフローとしてテストする
- 手書き修正とAgentへの再相談は、異なるユーザー操作としてそれぞれ確認する
- 異常系は、認証切れ、通信切断、冪等性、更新競合、Tenant境界、X投稿結果不明に限定する
- 同じ確認を画面別またはAPI別に重複させない

## 5. テスト環境

| 項目 | 条件 |
| --- | --- |
| Browser | CIで採用するChromiumの固定Version |
| Viewport | 自動E2EはDesktop 1440 x 900を基本とする |
| Frontend | E2E対象のNext.js Build |
| Backend | E2E対象のFastAPI Build |
| Database | PostgreSQL + pgvector。ケースごとに既知の状態へ初期化する |
| Clock | `2026-09-21T10:00:00Z`を基準に固定・進行可能にする |
| X API | 投稿成功、結果不明、指標取得を制御できるFake |
| GA4 Data API | 流入ユーザー数と一時失敗を制御できるFake |
| LLM・Agent | Tool Callと最終回答を固定できるFake |
| Embedding | 入力に対応する固定Vectorを返すFake |
| Web検索・取得 | 固定結果を返し、外部Networkへ接続しないFake |

実行時に本物の外部Credentialを設定しない。E2E環境から許可していない外部Hostへの通信を遮断する。

## 6. 共通テストデータ

### 6.1 アカウント

| 識別子 | 所属 | 用途 |
| --- | --- | --- |
| `MARKETER_A` | `COMPANY_A` | 基本操作を行う利用者 |
| `MARKETER_A2` | `COMPANY_A` | 同一会社の業務データ共有と、他マーケターのSession非公開確認 |
| `MARKETER_B` | `COMPANY_B` | Tenant境界の確認 |

テスト用パスワードはE2E環境のSecretまたはFixtureから注入し、本書、Source、Logへ平文で保存しない。

### 6.2 固定入力

| 項目 | 値 |
| --- | --- |
| 施策依頼 | `経験者Webエンジニア採用の施策を考えて` |
| 施策タイトル | `経験者Webエンジニア採用` |
| 手動修正後の目的 | `応募数を月20件まで増やす` |
| 再相談指示 | `リモート勤務の訴求を強めて` |
| 投稿依頼 | `この施策のX投稿案を作成して` |
| 手動修正後の投稿本文 | `フルリモートで働けるWebエンジニアを募集しています。` |
| 遷移先URL | `https://example.com/jobs/engineer` |
| X投稿ID | `1840000000000000000` |
| X初週PV | `1200` |
| GA4流入ユーザー数 | `45` |

### 6.3 Agent Fakeの基本応答

- 施策依頼では、`run_campaign_planner`の後に`propose_campaign`を実行し、編集可能な施策案を返す
- 再相談では、現在のフォーム値を引き継ぎ、リモート勤務の訴求を追加した新しい施策案を返す
- 投稿依頼では、`run_content_creator`の後に`propose_x_post`を実行し、編集可能な投稿案を返す
- 過去記憶を利用するケースでは、`search_long_term_memory`の結果を参照したことを識別可能な固定提案を返す
- Fakeは施策保存、X投稿、記憶削除を直接実行しない

## 7. テストケース一覧

| ID | 区分 | テスト名 | 優先度 |
| --- | --- | --- | --- |
| E2E-001 | 正常系 | ログインして新しい会話を開始する | 必須 |
| E2E-002 | 正常系 | 過去の会話を開いて再開する | 必須 |
| E2E-003 | 正常系 | 施策案を手動修正して承認する | 必須 |
| E2E-004 | 正常系 | Agentと再相談して施策案を承認する | 必須 |
| E2E-005 | 正常系 | 保存済み施策をAgent経由で更新する | 必須 |
| E2E-006 | 正常系 | 施策詳細から直接編集する | 必須 |
| E2E-007 | 正常系 | X投稿案を手動修正して公開する | 必須 |
| E2E-008 | 正常系 | 施策と投稿を検索して参照する | 必須 |
| E2E-009 | 正常系 | 公開後の計測結果を確認する | 必須 |
| E2E-010 | 正常系 | 評価記憶を次の施策提案に利用する | 必須 |
| E2E-011 | 正常系 | 不要な記憶を削除する | 必須 |
| E2E-012 | 正常系 | ログアウトする | 必須 |
| E2E-E01 | 異常系 | 認証切れ後に再ログインして元画面へ戻る | 必須 |
| E2E-E02 | 異常系 | Agent通信切断後に既存Turnを復元する | 必須 |
| E2E-E03 | 異常系 | 承認と公開を再送しても重複実行しない | 必須 |
| E2E-E04 | 異常系 | 施策編集の競合から入力を保持して復帰する | 必須 |
| E2E-E05 | 異常系 | 存在しないデータと別会社データを同じ表示にする | 必須 |
| E2E-E06 | 異常系 | X投稿結果不明時に自動再投稿しない | 必須 |

## 8. 正常系テストケース

### E2E-001 ログインして新しい会話を開始する

**事前条件**

- `MARKETER_A`が未ログインである
- `MARKETER_A`が事前登録済みである

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | `/login`を開く | Email、Password、ログインボタンが表示される。業務画面は表示されない | SC-01 `/login` | `GET /api/v1/auth/me` |
| 2 | ユーザー | `MARKETER_A`のEmailとPasswordを入力し、ログインする | ログイン処理中は二重送信できない。成功後に`/chat`へ移動する | SC-01、SC-02 `/chat` | `POST /api/v1/auth/login` |
| 3 | システム | 認証済み画面を表示する | グローバルナビとログイン中のEmailが表示される | SC-02 | `GET /api/v1/auth/me`、`GET /api/v1/agent-sessions` |
| 4 | ユーザー | 「新しい会話」を選択する | `/chat/new`へ移動し、空の会話とメッセージ入力欄が表示される | SC-02 `/chat/new` | なし |
| 5 | ユーザー | 固定の施策依頼を入力して送信する | 親Sessionが作成され、URLが`/chat/{session_id}`になる。送信中は入力と送信ボタンが実行中状態になる | SC-02 `/chat/{session_id}` | `POST /api/v1/agent-sessions`、`POST /api/v1/agent-sessions/{session_id}/turns` |
| 6 | システム | Agent Turnを完了する | ユーザーの依頼、Agent回答、施策提案フォームが順番どおり表示される。会話一覧に依頼の先頭を使ったタイトルが表示される | SC-02 | Turn送信のSSE、`GET /api/v1/agent-sessions` |

**最終確認**

- `MARKETER_A`を所有者とする親Sessionが1件作成されている
- `chat` Turnが1件作成され、`user_message`と提案結果が保存されている
- Agent Fakeの施策提案フローが1回だけ実行されている
- Campaignはまだ保存されていない

### E2E-002 過去の会話を開いて再開する

**事前条件**

- `MARKETER_A`でログイン済みである
- `MARKETER_A`に複数の親Sessionと完了済みTurnが存在する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | `/chat`を開く | 親Sessionだけが最終更新日時の新しい順に表示される | SC-02 `/chat` | `GET /api/v1/agent-sessions?limit=20` |
| 2 | ユーザー | 過去の会話を選択する | `/chat/{session_id}`へ移動し、選択した会話の最新履歴がTurn番号順に表示される | SC-02 `/chat/{session_id}` | `GET /api/v1/agent-sessions/{session_id}` |
| 3 | ユーザー | 古い履歴を追加表示する | 既存表示を重複させず、古いTurnが先頭側へ追加される | SC-02 | `GET /api/v1/agent-sessions/{session_id}?before_turn_number=...` |
| 4 | ユーザー | 続きのメッセージを入力して送信する | 新しいTurnが末尾へ追加され、既存履歴が維持される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 5 | システム | Agent Turnを完了する | 会話一覧の対象Sessionが先頭へ移動し、更新後の履歴が再表示しても維持される | SC-02 | `GET /api/v1/agent-sessions`、`GET /api/v1/agent-sessions/{session_id}` |

**最終確認**

- 新しいTurnは選択した親Sessionにだけ追加されている
- 子Sessionと他マーケターのSessionは会話一覧へ表示されない
- 履歴の追加読込でTurnの欠落と重複がない

### E2E-003 施策案を手動修正して承認する

**事前条件**

- `MARKETER_A`でログイン済みである
- 新しい会話を開始できる
- Agent Fakeが固定の施策案を返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 新しい会話で固定の施策依頼を送信する | Agentの進捗が表示され、完了後に編集可能な施策フォームが表示される | SC-02 | `POST /api/v1/agent-sessions`、`POST /api/v1/agent-sessions/{session_id}/turns` |
| 2 | ユーザー | 施策の目的を固定の手動修正後の目的へ変更する | 入力値だけが即時更新される。Agent Turnと業務APIは実行されない | SC-02 | なし |
| 3 | ユーザー | 「承認して保存」を選択する | 承認対象の最終フォーム値を確認できる | SC-02 | なし |
| 4 | ユーザー | 最終承認を確定する | 保存中は再押下できない。手動修正後の値と新しい`Idempotency-Key`が送信される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/campaigns` |
| 5 | システム | 保存結果を表示する | 保存完了通知と施策詳細への導線が表示される | SC-02 | 同上 |
| 6 | ユーザー | 施策詳細への導線を選択する | 修正後の目的を含む施策全項目が表示される | SC-05 `/campaigns/{campaign_id}` | `GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- CampaignとCampaign Embeddingが各1件作成されている
- 承認時の最終Requestと成功した`api_result`が同じ親Sessionの`approval` Turnへ保存されている
- 手動編集だけではAgent Fakeが追加実行されていない
- 承認処理ではLLMとAgent Toolが実行されていない

### E2E-004 Agentと再相談して施策案を承認する

**事前条件**

- `MARKETER_A`でログイン済みである
- 施策提案フォームが表示されている

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 施策フォームで「Agentと再相談」を選択する | 現在のフォーム値と修正指示を入力できる | SC-02 | なし |
| 2 | ユーザー | 固定の再相談指示を入力して送信する | 現在のフォーム値と指示が新しいメッセージとして送信され、進捗が表示される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 3 | システム | 再提案を返す | 新しい提案フォームへ置き換わり、リモート勤務の訴求が含まれる | SC-02 | Turn送信のSSE |
| 4 | ユーザー | 再提案を最終承認する | 再提案の値が保存され、成功通知が表示される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/campaigns` |
| 5 | ユーザー | 保存した施策を開く | 再提案後の値が施策詳細へ表示される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- 初回提案と再提案は別の`chat` Turnとして保存されている
- 再相談では新しい使い捨て子Sessionが作成されている
- Campaignは最終承認時に1件だけ作成されている
- 初回提案の値ではなく、再提案の最終値が保存されている

### E2E-005 保存済み施策をAgent経由で更新する

**事前条件**

- `MARKETER_A`でログイン済みである
- `COMPANY_A`に未ArchiveのCampaignが存在する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 施策詳細で「変更を相談する」を選択する | 対象施策を引き継いだチャット画面へ移動する | SC-05、SC-02 | `GET /api/v1/campaigns/{campaign_id}` |
| 2 | ユーザー | 施策変更の依頼を送信する | Agentが対象Campaignを参照し、更新用の施策フォームを表示する | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 3 | ユーザー | 提案内容を確認して最終承認する | `id`と提案取得時点の`expected_updated_at`を含む更新Requestが送信される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/campaigns` |
| 4 | システム | 更新結果を表示する | 新規施策を作らず、更新した施策への導線が表示される | SC-02 | 同上 |
| 5 | ユーザー | 施策詳細を開く | 更新内容と新しい更新日時が表示される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- Campaignの件数は増えず、対象行が更新されている
- 内容が変わった場合はCampaign Embeddingが同期されている
- 更新の最終Requestと結果が承認Turnへ保存されている

### E2E-006 施策詳細から直接編集する

**事前条件**

- `MARKETER_A`でログイン済みである
- `COMPANY_A`に未ArchiveのCampaignが存在する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 施策詳細を開く | 全項目、更新日時、編集操作が表示される | SC-05 `/campaigns/{campaign_id}` | `GET /api/v1/campaigns/{campaign_id}` |
| 2 | ユーザー | 「編集」を選択する | 現在値を初期値とする編集フォームが表示される | SC-05 | なし |
| 3 | ユーザー | 目的を変更して保存する | 取得時点の`updated_at`を`expected_updated_at`として送信し、保存中は再押下できない | SC-05 | `PUT /api/v1/campaigns/{campaign_id}` |
| 4 | システム | 保存結果を表示する | 編集フォームが閉じ、変更後の値と更新日時が表示される | SC-05 | 同上 |
| 5 | ユーザー | ページを再読み込みする | 変更後の値が維持される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- 対象CampaignとEmbeddingが更新されている
- Agent Session、Turn、Item、冪等性レコードは作成されていない
- LLM、Agent Tool、外部APIは呼び出されていない

### E2E-007 X投稿案を手動修正して公開する

**事前条件**

- `MARKETER_A`でログイン済みである
- `COMPANY_A`に未Archiveの承認済みCampaignが存在する
- X Fakeは固定のX投稿IDを返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 施策詳細で「この施策で投稿案を作る」を選択する | 対象施策を引き継いだチャット画面へ移動する | SC-05、SC-02 | `GET /api/v1/campaigns/{campaign_id}` |
| 2 | ユーザー | 固定の投稿依頼を送信する | Agentの進捗後、編集可能な投稿フォームが表示される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 3 | ユーザー | 本文を固定の手動修正後の投稿本文へ変更する | フォーム値と文字数表示が更新され、Agentは再実行されない | SC-02 | なし |
| 4 | ユーザー | 「承認して公開」を選択し、最終確認する | 対象施策、本文、遷移先URLを確認できる | SC-02 | なし |
| 5 | ユーザー | 公開を確定する | 公開中は再押下できない。最終値と新しい`Idempotency-Key`が送信される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/x/posts` |
| 6 | システム | 公開結果を表示する | 公開成功通知、X投稿ID、投稿詳細への導線が表示される | SC-02 | 同上 |
| 7 | ユーザー | 投稿詳細への導線を選択する | 最終本文、対象施策、UTM付きURL、計測待ち状態が表示される | SC-07 `/posts/{post_id}` | `GET /api/v1/posts/{post_id}` |

**最終確認**

- X FakeはUTM付きURLを含む投稿を1回だけ受信している
- Post、Post Embedding、Tracking、`pending`のMetricsが各1件作成されている
- `utm_source=x`、`utm_medium=social`、Campaign ID、固定Action IDが保存されている
- 最終Request、X投稿結果、成功した`api_result`が承認Turnと冪等性レコードへ保存されている
- 公開処理ではLLMとAgent Toolが実行されていない

### E2E-008 施策と投稿を検索して参照する

**事前条件**

- `MARKETER_A`でログイン済みである
- `COMPANY_A`に複数の施策と公開済み投稿が存在する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | グローバルナビから「施策」を選択する | 保存済み施策だけが新しい順に表示される | SC-04 `/campaigns` | `GET /api/v1/campaigns` |
| 2 | ユーザー | 固定の検索語を入力して検索する | 条件がURLへ反映され、意味検索結果だけが表示される | SC-04 | `GET /api/v1/campaigns?query=...` |
| 3 | ユーザー | 対象施策を選択する | 全項目、関連投稿、関連記憶、Metrics集計が表示される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |
| 4 | ユーザー | 関連投稿を選択する | 投稿本文、UTM、Metrics、対象施策が表示される | SC-07 | `GET /api/v1/posts/{post_id}` |
| 5 | ユーザー | グローバルナビから「投稿」を選択する | 公開済み投稿だけが表示される | SC-06 `/posts` | `GET /api/v1/posts` |
| 6 | ユーザー | 施策で絞り込み、PVの多い順へ変更する | 条件がURLへ反映され、対象施策の投稿が指定順で表示される | SC-06 | `GET /api/v1/campaigns`、`GET /api/v1/posts?campaign_id=...&sort=x_pv_count&order=desc` |
| 7 | ユーザー | 次のページを読み込む | 先頭ページと重複せず、Snapshotに基づく続きが表示される | SC-06 | `GET /api/v1/posts?cursor=...` |

**最終確認**

- URLを再読み込みしても検索、絞り込み、並び順が維持される
- `COMPANY_B`の施策と投稿は結果へ含まれない
- 検索と参照では業務データとAgent履歴が変更されない

### E2E-009 公開後の計測結果を確認する

**事前条件**

- `MARKETER_A`でログイン済みである
- E2E-007相当の公開済み投稿と`pending`のMetricsが存在する
- Clockを投稿公開から7日後へ進められる
- X FakeはPV `1200`、GA4 Fakeは流入ユーザー数`45`を返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 投稿詳細を開く | 計測前は計測待ちと予定日時が表示される | SC-07 | `GET /api/v1/posts/{post_id}` |
| 2 | テスト環境 | Clockを`scheduled_at`以降へ進め、正しいCron SecretでCronを実行する | 対象投稿がClaimされ、XとGA4のFakeが各1回呼ばれる | なし | `GET /api/cron/post-metrics` |
| 3 | テスト環境 | 同じ条件でCronを再実行する | 完了済みMetricsと生成済み記憶が重複処理されない | なし | `GET /api/cron/post-metrics` |
| 4 | ユーザー | 投稿詳細を再読み込みする | 初週PV `1200`、流入ユーザー数`45`、計測日時が表示される | SC-07 | `GET /api/v1/posts/{post_id}` |
| 5 | ユーザー | グローバルナビから「計測結果」を選択する | 全体集計と施策別集計に対象投稿の値が反映される | SC-08 `/metrics` | `GET /api/v1/metrics` |
| 6 | ユーザー | 期間を公開日を含む範囲へ変更する | 条件がURLへ反映され、集計対象と値が更新される | SC-08 | `GET /api/v1/metrics?published_from=...&published_to=...` |
| 7 | ユーザー | 施策を選択する | 対象の施策詳細へ移動し、投稿ごとのPVと集計が表示される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- Metricsが`completed`になり、`x_pv_count=1200`、`landing_user_count=45`である
- 流入率が保存値または同じ計算規則から正しく表示される
- 評価記憶とCampaign・Postへの関連が1組だけ作成されている
- Cron再実行で外部呼び出しと記憶が重複しない

### E2E-010 評価記憶を次の施策提案に利用する

**事前条件**

- `MARKETER_A`でログイン済みである
- E2E-009相当のMetricsと評価記憶が存在する
- Agent Fakeは記憶の参照結果を反映した固定提案を返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | グローバルナビから「記憶」を選択する | 評価記憶と関連施策・投稿が表示される | SC-09 `/memories` | `GET /api/v1/memories` |
| 2 | ユーザー | 評価記憶の関連施策を選択する | 評価元の施策詳細が表示される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |
| 3 | ユーザー | 新しい会話を開始し、類似する施策を依頼する | Agentの進捗後、過去結果を反映した施策案が表示される | SC-02 | `POST /api/v1/agent-sessions`、`POST /api/v1/agent-sessions/{session_id}/turns` |
| 4 | ユーザー | 提案を最終承認する | 新しいCampaignが保存され、詳細への導線が表示される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/campaigns` |
| 5 | ユーザー | 新しい施策詳細を開く | 過去結果を反映した最終内容が表示される | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- Agent Turn内で`search_long_term_memory`が実行され、対象記憶がContextへ利用されている
- X・GA4 Credential、Cookie、API KeyはAgent Fakeの入力に含まれない
- 過去のCampaignを変更せず、新しいCampaignが作成されている

### E2E-011 不要な記憶を削除する

**事前条件**

- `MARKETER_A`でログイン済みである
- `COMPANY_A`にCampaignとPostへ関連付いた長期記憶が存在する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 記憶一覧を開く | 長期記憶、関連施策、関連投稿、削除操作が表示される | SC-09 | `GET /api/v1/memories` |
| 2 | ユーザー | 対象記憶の「削除」を選択する | 削除対象と取り消せないことを示す確認Dialogが表示される | SC-09 | なし |
| 3 | ユーザー | DialogをCancelする | 記憶が一覧に残り、削除APIは呼ばれない | SC-09 | なし |
| 4 | ユーザー | 再度「削除」を選択して確定する | 削除中は再操作できず、成功後に対象記憶が一覧から除かれる | SC-09 | `DELETE /api/v1/memories/{memory_id}` |
| 5 | ユーザー | 関連していた施策と投稿を開く | 施策と投稿は残り、削除した記憶だけが関連情報から消えている | SC-05、SC-07 | `GET /api/v1/campaigns/{campaign_id}`、`GET /api/v1/posts/{post_id}` |
| 6 | ユーザー | 記憶一覧で削除した内容を検索する | 削除した記憶が検索結果へ表示されない | SC-09 | `GET /api/v1/memories?query=...` |

**最終確認**

- 記憶、Embedding、Campaign・Postとの関連行が削除されている
- Campaign、Post、Metrics、過去のAgent履歴は削除されていない
- Agent Session、Turn、冪等性レコード、LLM呼び出しは追加されていない
- 次回Cronでも削除した評価記憶を再生成しない

### E2E-012 ログアウトする

**事前条件**

- `MARKETER_A`でログイン済みである

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 認証済み画面でグローバルナビを開く | ログイン中のEmailとログアウト操作が表示される | 全認証済み画面 | `GET /api/v1/auth/me` |
| 2 | ユーザー | 「ログアウト」を選択する | ログアウト処理後に`/login`へ移動する | 全認証済み画面、SC-01 | `POST /api/v1/auth/logout` |
| 3 | ユーザー | Browserの戻る操作で直前の業務画面へ戻る | 業務データを表示せず、再び`/login`へ移動する | SC-01 | `GET /api/v1/auth/me` |
| 4 | ユーザー | 保護されたURLを直接開く | ログイン画面へ移動し、元のURLがログイン後の戻り先として保持される | SC-01 | `GET /api/v1/auth/me` |

**最終確認**

- 認証CookieとCSRF Token CookieがBrowserから削除されている
- ログアウトによって業務データとAgent履歴は変更されていない

## 9. 異常系テストケース

### E2E-E01 認証切れ後に再ログインして元画面へ戻る

**事前条件**

- `MARKETER_A`でログインし、施策詳細を表示している
- テスト環境から認証Cookieを期限切れにできる

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | テスト環境 | 認証Cookieを期限切れにする | Browser上の表示は維持されるが、次の認証確認は失敗する状態になる | SC-05 | なし |
| 2 | ユーザー | ページを再読み込みする | 業務データを表示せず、`/login`へ移動する。元の施策詳細URLが保持される | SC-05、SC-01 | `GET /api/v1/auth/me` |
| 3 | ユーザー | 正しい認証情報で再ログインする | 元の施策詳細へ戻り、対象施策が表示される | SC-01、SC-05 | `POST /api/v1/auth/login`、`GET /api/v1/campaigns/{campaign_id}` |

**最終確認**

- 認証失敗によってAgent履歴と業務データが変更されていない
- 期限切れCookieが新しいログイン結果で置き換えられている

### E2E-E02 Agent通信切断後に既存Turnを復元する

**事前条件**

- `MARKETER_A`で親Sessionを開いている
- Agent Fakeの完了を遅延させ、SSEを途中で切断できる

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 固定の施策依頼を送信する | `turn_started`を受信し、進捗が表示される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 2 | テスト環境 | `turn_finished`より前にSSE接続を切断する | UIは同じメッセージを自動再送せず、結果確認中を表示する | SC-02 | なし |
| 3 | システム | Session履歴とTurn状態を確認する | 既存TurnのIDを使って`pending`または`running`の間だけ状態を確認する | SC-02 | `GET /api/v1/agent-sessions/{session_id}`、`GET /api/v1/agent-sessions/{session_id}/turns/{turn_id}` |
| 4 | テスト環境 | Agent Fakeを完了させる | UIが完了済みTurnを取得し、回答と提案フォームを表示する | SC-02 | Turn取得API |

**最終確認**

- `user_message`とAgent Turnは各1件だけ存在する
- Agent Fakeと施策提案Toolは各1回だけ実行されている
- 通信切断を理由とする2つ目のTurnが作成されていない

### E2E-E03 承認と公開を再送しても重複実行しない

**事前条件**

- `MARKETER_A`の2つの親Sessionに、施策案と投稿案がそれぞれ表示されている
- 最初のResponseをBrowserへ返さず、サーバー処理だけを完了させられる

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 施策案を最終承認する | UIが1つの`Idempotency-Key`を生成して送信する | SC-02 | `POST /api/v1/agent-sessions/{session_id}/campaigns` |
| 2 | テスト環境 | 保存完了後、Responseだけを切断する | UIは結果不明を表示し、新しいキーで自動承認しない | SC-02 | 同上 |
| 3 | ユーザー | 画面が提示する再確認操作を行う | 同じキーと同じRequestが送信され、元の成功結果が表示される | SC-02 | 同上 |
| 4 | ユーザー | 投稿案がある親Sessionへ切り替え、最終承認して公開する | UIが投稿承認用の1つのキーを生成して送信する | SC-02 | `GET /api/v1/agent-sessions/{session_id}`、`POST /api/v1/agent-sessions/{session_id}/x/posts` |
| 5 | テスト環境 | X成功とDB保存完了後、Responseだけを切断する | UIは新しいキーで自動公開せず、結果確認または同じキーでの再送を提示する | SC-02 | 同上 |
| 6 | ユーザー | 同じ操作の結果を再取得する | 元の公開成功結果と投稿詳細への導線が表示される | SC-02 | 同上 |

**最終確認**

- Campaign、Post、承認Turnは操作ごとに各1件だけ作成されている
- X Fakeの投稿呼び出しは1回だけである
- 同じキーの再送では保存済みのStatusとResponseが返される

### E2E-E04 施策編集の競合から入力を保持して復帰する

**事前条件**

- `MARKETER_A`と`MARKETER_A2`で同じCampaignの編集画面を開いている
- 両者は同じ`updated_at`を保持している

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `MARKETER_A2` | 施策を変更して先に保存する | 保存が成功し、Campaignの`updated_at`が更新される | SC-05 | `PUT /api/v1/campaigns/{campaign_id}` |
| 2 | `MARKETER_A` | 別の内容を入力して保存する | `CAMPAIGN_CONFLICT`が表示され、入力した内容が失われない | SC-05 | `PUT /api/v1/campaigns/{campaign_id}` |
| 3 | `MARKETER_A` | 最新内容の取得を選択する | 最新の保存内容と自分の入力内容を確認して再編集できる | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |
| 4 | `MARKETER_A` | 内容を調整して再度保存する | 新しい`expected_updated_at`で保存が成功する | SC-05 | `PUT /api/v1/campaigns/{campaign_id}` |

**最終確認**

- 競合したRequestではCampaignとEmbeddingが変更されていない
- 再保存した最終値だけが反映されている
- 競合と再保存でAgent履歴は作成されていない

### E2E-E05 存在しないデータと別会社データを同じ表示にする

**事前条件**

- `MARKETER_A`でログイン済みである
- `COMPANY_B`にCampaign、Post、親Sessionが存在する
- `MARKETER_A2`に親Sessionが存在する
- 存在しない各IDを用意する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 存在しないCampaign IDのURLを開く | 「見つかりません」が表示され、内部情報を表示しない | SC-05 | `GET /api/v1/campaigns/{campaign_id}` |
| 2 | ユーザー | `COMPANY_B`のCampaign IDのURLを開く | Step 1と同じStatus、Error Code、画面文言になる | SC-05 | 同上 |
| 3 | ユーザー | 存在しないPostと`COMPANY_B`のPostを順に開く | どちらも同じ「見つかりません」表示になる | SC-07 | `GET /api/v1/posts/{post_id}` |
| 4 | ユーザー | `COMPANY_B`のSession URLを開く | 会話内容を表示せず、「見つかりません」になる | SC-02 | `GET /api/v1/agent-sessions/{session_id}` |
| 5 | ユーザー | 同じ会社の`MARKETER_A2`が所有するSession URLを開く | Step 4と同じ「見つかりません」表示になり、会話内容を表示しない | SC-02 | `GET /api/v1/agent-sessions/{session_id}` |

**最終確認**

- `COMPANY_B`のデータは一切変更されていない
- Response Body、画面、Browser Consoleからデータの存在を推測できない
- Sessionは同一会社でも所有するマーケター本人以外には表示されない

### E2E-E06 X投稿結果不明時に自動再投稿しない

**事前条件**

- `MARKETER_A`で投稿案を表示している
- X Fakeは投稿Requestを受信した後に結果不明のTimeoutを返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 投稿案を最終承認して公開する | 投稿Requestが1回送信される | SC-02 | `POST /api/v1/agent-sessions/{session_id}/x/posts` |
| 2 | システム | X Fakeから結果不明を受け取る | 自動再投稿せず、公開結果を確認できない旨と手動照合が必要なことを表示する | SC-02 | 同上 |
| 3 | ユーザー | ページを再読み込みする | 成功済み投稿として表示せず、結果不明状態と次の操作を確認できる | SC-02 | `GET /api/v1/agent-sessions/{session_id}` |
| 4 | ユーザー | 同じ公開操作を再度選択する | 新しい公開を開始せず、未解決の投稿があることを表示する | SC-02 | `POST /api/v1/agent-sessions/{session_id}/x/posts` |

**最終確認**

- X Fakeへの投稿呼び出しは1回だけである
- 冪等性レコードは`outcome_unknown`で、同じ内容のPostは作成されていない
- Metrics、Tracking、Post Embeddingは作成されていない
- 手動照合前に成功または失敗へ推測で確定していない

## 10. 手動動作確認

自動E2Eと同じ業務結果を再確認するのではなく、視覚、操作感、支援技術、実行環境に依存する項目を確認する。

### 10.1 共通UI

| ID | 操作 | 確認項目 | 対象画面 |
| --- | --- | --- | --- |
| MAN-001 | Desktop、Tablet、320px幅で主要フローを表示する | 内容の欠落、重なり、意図しない横Scrollがない | SC-01、SC-02、SC-04からSC-09 |
| MAN-002 | Browserを200%へZoomする | 入力、主要操作、Error、Navigationへ到達できる | 全画面 |
| MAN-003 | Mouseを使わずTab、Shift+Tab、Enter、Space、Escapeで操作する | Focus順、Focus表示、Dialog、Form送信、Navigationが適切である | 全画面 |
| MAN-004 | Loading、Empty、Error、Not Foundを順に表示する | 状態の意味と次の操作が視覚的かつ文言で分かる | 全画面 |
| MAN-005 | 長い会話、施策、投稿、Error文を表示する | 省略規則が一貫し、必要な全文へ到達でき、Layoutが崩れない | SC-01、SC-02、SC-04からSC-09 |
| MAN-006 | `prefers-reduced-motion: reduce`で操作する | 不要なAnimationが抑制され、状態変化は認識できる | 全画面 |

### 10.2 FormとAgent操作

| ID | 操作 | 確認項目 | 対象画面 |
| --- | --- | --- | --- |
| MAN-007 | 必須入力を空にして送信する | Errorが入力と関連付けられ、最初のErrorへFocusが移る | SC-01、SC-02、SC-05 |
| MAN-008 | Passwordの表示・非表示を切り替える | 値、選択範囲、Focusを維持する | SC-01 |
| MAN-009 | Agentへメッセージを送信する | 進捗の開始・完了、現在の処理、送信不可状態を判別できる | SC-02 |
| MAN-010 | 手動修正、再相談、最終承認を順に行う | 3操作を誤認せず、承認前に最終値を確認できる | SC-02 |
| MAN-011 | Browser更新、戻る、進むを行う | 保存済み状態と未保存状態が混在せず、二重承認しない | SC-02、SC-05 |

### 10.3 一覧・詳細・計測

| ID | 操作 | 確認項目 | 対象画面 |
| --- | --- | --- | --- |
| MAN-012 | 検索、絞り込み、並び替え、追加読込を行う | 現在条件、件数の増加、追加位置が理解できる | SC-04、SC-06、SC-08、SC-09 |
| MAN-013 | Pending、Completed、FailedのMetricsを表示する | 状態と値の有無を色だけに依存せず判別できる | SC-05からSC-08 |
| MAN-014 | UTM付きURLのCopyを行う | 成功と失敗が通知され、Copy対象が分かる | SC-07 |
| MAN-015 | 記憶削除Dialogを開閉する | 対象、影響、Cancel、確定操作が明確で、FocusがDialog内で管理される | SC-09 |

### 10.4 Browser・API・Log

| ID | 操作 | 確認項目 | 対象 |
| --- | --- | --- | --- |
| MAN-016 | 全正常系を実行してDeveloper Toolsを確認する | 想定外のConsole Error、Hydration Error、失敗Requestがない | Browser |
| MAN-017 | 認証と状態変更APIを確認する | Cookie属性、Origin、CSRF Headerが設計どおりである | Browser Network |
| MAN-018 | Agent SSEを確認する | Event順、Content-Type、Cache制御、Keep-aliveが設計どおりである | Browser Network |
| MAN-019 | E2E実行中の構造化Logを確認する | `request_id`、`session_id`、`turn_id`で処理を追跡できる | Backend Log |
| MAN-020 | 認証・Agent・CronのLogを検索する | Password、Cookie、Token、API Key、会話本文、投稿本文、GA4 Filter値が出力されていない | Backend Log |
| MAN-021 | E2E環境の外部通信を確認する | 許可したFake以外の外部Hostへ通信していない | Network Log |

## 11. 合否基準

### 11.1 テストケース

- 全Stepの操作を実行でき、確認項目をすべて満たすこと
- 最終確認のUI、API、永続化、外部作用がすべて一致すること
- 想定外のBrowser Console Error、未処理例外、5xxがないこと
- ケース終了後に未完了のTurn、Lease、処理中の冪等性レコードが残らないこと。ただし、結果不明を確認するE2E-E06は除く

### 11.2 リリース判定

- 優先度「必須」の自動E2Eがすべて成功すること
- 手動動作確認で操作不能、情報漏洩、外部への意図しない副作用がないこと
- 失敗を既知問題として許容する場合は、対象ケース、利用者影響、回避策、Issueを記録すること

## 12. 実装状況

本書はv0.1の完成形を対象とする。現時点の実装ではLanding PageとHealth API以外の主要画面・業務API・E2E Runnerが未実装であるため、各ケースは対象機能とテスト基盤の実装後に実行可能となる。

E2E Runner、起動Command、Fixtureの配置、Artifactの保存先は、テスト基盤の採用時に本節へ追記する。
