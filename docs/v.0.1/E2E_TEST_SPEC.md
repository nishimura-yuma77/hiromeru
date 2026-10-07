# E2Eテスト仕様書

## 1. 目的

本書は、Hiromeru v0.1の主要なユーザー操作フローを、Frontend、Backend、PostgreSQLを横断して確認するE2Eテストの仕様を定義する。

テストは正常系の業務フローを優先し、異常系は、二重実行や外部公開など利用者または業務データへの影響が大きいものに限定する。各テストケースは、具体的な操作と、その操作に対応する確認項目、関連画面、関連APIを必須とする。

## 2. 対象範囲

### 2.1 対象

- `SCREEN_DESIGN.md`のSC-01、SC-02、SC-04からSC-12
- 会社・責任者の初期登録と管理ユーザーのログイン、招待から登録・ユーザー管理、および施策作成、X投稿公開、計測、長期記憶の利用までのユーザーフロー
- BrowserからNext.js、FastAPI、PostgreSQLまでの接続
- Agent Turn、承認API、参照API、Cronによる状態変化
- 認証Cookieと認証世代、CSRF、管理権限、会社・本人の会話履歴のデータ境界
- X、GA4、LLM、Embedding、SESのFakeを含む外部連携境界

### 2.2 対象外

- Component、関数、Repository単位の単体テスト
- APIごとの入力境界値を網羅するテスト
- ブラウザやOSの全組み合わせを対象とする互換性テスト
- 負荷、長時間稼働、侵入、脆弱性診断
- Vercel WAFによるログイン回数制限そのものの動作
- 実際のX、GA4、OrcaRouterへの接続
- 実際のAWS SESへの送信と配達確認（E2Eでは送信受付結果をSES Fakeで制御する）
- `SCREEN_DESIGN.md`で`/chat`への遷移が定義されている`/`と、現行実装のLanding Page

## 3. 参照文書

| 文書 | 本書で参照する内容 |
| --- | --- |
| `REQUIREMENTS.md` | MVPの基本フロー、非機能要件 |
| `USECASE.md` | 会社・責任者登録、自社ユーザー招待・管理、施策作成・更新、X投稿作成・公開のユーザー起点フロー |
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
- X、GA4、LLM、Embedding、Web検索・取得、SESは決定論的なFakeへ差し替える。招待メールはSES Fakeが生成したリンクをテスト環境で取得してBrowserから開く
- テストから業務APIを直接呼び出して主操作を省略しない
- API直接呼び出しとDB直接操作は、事前条件の準備、外部障害の注入、事後結果の確認だけに使用する
- 管理画面に入力欄のない他社IDや禁止対象の拒否は、Browserの認証Cookie・CSRF Tokenを使ってAPIへRequestし、画面操作後の認可の事後確認として検証してよい
- 各ケースは独立して実行でき、別ケースの実行結果へ依存しない
- 複数ユーザーを同じケースで操作する場合、ユーザーごとに独立したBrowser Contextを用い、CookieとQuery Cacheを共有しない
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
- 異常系は、認証切れ、通信切断、冪等性、更新競合、Tenant・本人の会話境界、X投稿結果不明に加え、招待リンクの失効、管理権限、利用停止・再開、SES送信失敗・結果不明を対象とする
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
| SES | 受付成功とMessageId、明確なスロットリング・失敗、5xx・408・応答なし・処理中断を制御できるFake。送信回数と招待リンクを検証可能にする |

実行時に本物の外部Credentialを設定しない。E2E環境から許可していない外部Hostへの通信を遮断する。

## 6. 共通テストデータ

### 6.1 アカウント

| 識別子 | 所属 | 用途 |
| --- | --- | --- |
| `MARKETER_A` | `COMPANY_A` | 基本操作を行う利用者 |
| `MARKETER_A2` | `COMPANY_A` | 同一会社の業務データ共有と、他マーケターのSession非公開確認 |
| `MARKETER_B` | `COMPANY_B` | Tenant境界の確認 |
| `ADMIN_A` | `COMPANY_A` | 初期設定で作成する責任者。管理ユーザーのログイン、招待、停止禁止の確認 |
| `ADMIN_A2` | `COMPANY_A` | 責任者ではない管理ユーザー。本人・責任者への停止・種別変更禁止と同一会社内の境界確認 |
| `ADMIN_B` | `COMPANY_B` | 他社ユーザーに対する管理操作の境界確認 |
| `INVITEE_A` | `COMPANY_A` | 管理画面から招待する対象。ケースごとに新しい識別子を用意する |

テスト用パスワードは12～128文字・半角英大文字／小文字／数字／記号を各1文字以上含む値をE2E環境のSecretまたはFixtureから注入し、本書、Source、Logへ平文で保存しない。`MARKETER_A`など既存ケースの利用者は、対応する会社・責任者の初期登録後、招待登録が完了した状態をFixtureで準備してよい。

### 6.2 固定入力

| 項目 | 値 |
| --- | --- |
| 施策依頼（情報が揃っている） | `経験者Webエンジニア採用で応募ページへの流入を増やす施策を考えて` |
| 施策依頼（情報不足） | `新しい採用施策を考える` |
| 施策立案の質問 | `募集したい職種・必要なスキルは何ですか？`、`現在の採用課題または達成したい目的は何ですか？` |
| 質問への回答 | `経験者Webエンジニア`、`応募ページへの流入を増やしたい` |
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

- 情報が揃った施策依頼では、`run_campaign_planner`の後に`propose_campaign`を実行し、編集可能な施策案を返す
- 情報不足の施策依頼では、`run_campaign_planner`が`missing_information`を返し、親Agentが必要な質問を`ask_user`へ渡す。回答後は新しい子Sessionで再実行し、回答済み事項を聞き直さず施策案を返す
- 親Agentが子Agentを呼ぶ前に不足を判断した場合も、`ask_user`で質問を返せる。コンテンツ制作Agentが不足情報を返した場合も同じ質問カードを使う
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
| E2E-013 | 正常系 | 施策の情報不足を質問カードで確認してから提案する | 必須 |
| E2E-014 | 正常系 | 親Agentが子Agentを呼ばずに確認事項を尋ねる | 必須 |
| E2E-015 | 正常系 | 投稿案の情報不足を質問カードで確認する | 必須 |
| E2E-016 | 正常系 | 初期登録した責任者が管理画面とマーケター向け画面へログインする | 必須 |
| E2E-017 | 正常系 | マーケターユーザーを招待し、本人が登録・ログインする | 必須 |
| E2E-018 | 正常系 | 管理ユーザーを招待し、本人が登録・管理画面を開く | 必須 |
| E2E-019 | 正常系 | 自社ユーザーの一覧・ページ移動・表示名編集を行う | 必須 |
| E2E-020 | 正常系 | 利用中ユーザーを昇格・降格し、旧ログインと本人の会話履歴を確認する | 必須 |
| E2E-E01 | 異常系 | 認証切れ後に再ログインして元画面へ戻る | 必須 |
| E2E-E02 | 異常系 | Agent通信切断後に既存Turnを復元する | 必須 |
| E2E-E03 | 異常系 | 承認と公開を再送しても重複実行しない | 必須 |
| E2E-E04 | 異常系 | 施策編集の競合から入力を保持して復帰する | 必須 |
| E2E-E05 | 異常系 | 存在しないデータと別会社データを同じ表示にする | 必須 |
| E2E-E06 | 異常系 | X投稿結果不明時に自動再投稿しない | 必須 |
| E2E-E07 | 異常系 | 質問への回答Turnが失敗しても修正して再回答できる | 必須 |
| E2E-E08 | 異常系 | 利用停止・再開で旧ログインとリンクを失効させる | 必須 |
| E2E-E09 | 異常系 | 招待リンクの期限切れ・再送・一度きりの使用を確認する | 必須 |
| E2E-E10 | 異常系 | 管理権限・他社ユーザー・他人の会話履歴の境界を確認する | 必須 |
| E2E-E11 | 異常系 | SESの明確な失敗とスロットリング再試行を区別する | 必須 |
| E2E-E12 | 異常系 | SESの結果不明で自動再送せず、管理者が手動再送する | 必須 |
| E2E-E13 | 異常系 | 管理ユーザーの認証切れ後に管理者ログインへ戻る | 必須 |
| E2E-E14 | 異常系 | 禁止対象の種別変更と同時編集の競合を拒否する | 必須 |

## 8. 正常系テストケース

### E2E-001 ログインして新しい会話を開始する

**事前条件**

- `MARKETER_A`が未ログインである
- `MARKETER_A`が招待登録を完了している

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

### E2E-013 施策の情報不足を質問カードで確認してから提案する

**事前条件**

- `MARKETER_A`でログイン済みで、新しい会話を開始できる
- Agent Fakeが情報不足時には固定の`missing_information`、回答後には固定の施策案を返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 情報不足の施策依頼を送信する | 親Sessionが作成され、子Agentが`missing_information`を返し、親Agentが同じ親Turn内で`ask_user`を実行する。Campaignと提案フォームは作成されない | SC-02 | `POST /api/v1/agent-sessions`、`POST /api/v1/agent-sessions/{session_id}/turns` |
| 2 | システム | 質問カードを表示する | 2件の質問とそれぞれの回答欄が表示される。質問のTurnは`completed`、`clarification_request.content.answered = false`であり、質問文の重複した`assistant_message`はない | SC-02 | Turn送信のSSE |
| 3 | ユーザー | 通常のComposerから別の相談を送信する | 後続`user_message`が保存されても、元の質問カードの`answered = false`で回答欄は残る | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 4 | ユーザー | 回答を入力する | 空欄・各回答1,000文字超では送信できず、入力中は追加のAPIを呼び出さない。上限内の回答では送信できる | SC-02 | なし |
| 5 | ユーザー | 固定の質問への回答をまとめて送信する | 元の質問の`agent_turn_id`を`question_turn_id`に、回答を`question_index`順の配列にして、同じ親Sessionの新しいTurnへ送る。通常の`message`は併送せず、送信中は二重送信できない | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 6 | システム | 回答に基づく施策案を返す | 回答Turnの`user_message`に質問Turn IDと構造化した回答があり、新しい子Sessionの結果から編集可能な施策フォームが表示される。`turn_finished`直後に再読み込みなしで元カードの`answered`が`true`になり、回答Buttonが消える。既に回答した質問を繰り返さない | SC-02 | Turn送信のSSE |
| 7 | ユーザー | 画面を再読み込みする | 履歴から同じ質問と回答、施策フォームが復元され、元の質問カードは`answered = true`で再送できない | SC-02 | `GET /api/v1/agent-sessions/{session_id}` |

**最終確認**

- 情報不足Turnに成功した`run_campaign_planner`と`ask_user`のTool実行があり、`propose_campaign`はない
- 回答Turnでは再度`run_campaign_planner`を呼んで`propose_campaign`を実行し、提案はユーザーの承認前には業務テーブルへ保存されない
- 同じ質問Turnへの二度目の回答は`409 CLARIFICATION_ALREADY_ANSWERED`、他人・他Session・存在しない質問Turnを指定した場合は`404 CLARIFICATION_REQUEST_NOT_FOUND`となり、新しいTurnを作らない。欠けた回答、重複したIndex、`message`との併用は`400 INVALID_ARGUMENT`となる
- 親Agentが子Agentの質問を言い換えても`ask_user`を呼べる。入力が空、重複、4件以上または各200文字を超える場合は失敗Tool Resultになり、質問カードとして表示しない
- 回答送信で通信失敗または結果未確定になった場合は入力値を保持し、既存のTurn取得による復旧で送信結果を確認してから再送可否を決める
- 回答済みの質問へ`409 CLARIFICATION_ALREADY_ANSWERED`が返った場合は、元の質問Turnを再取得してカードを回答済みに同期する

### E2E-014 親Agentが子Agentを呼ばずに確認事項を尋ねる

**事前条件**

- `MARKETER_A`でログイン済みで、新しい会話を開始できる
- Agent Fakeが、依頼に必要な対象施策が特定できないと判断する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | `X投稿案を作りたい`と送信する | 親Agentが対象施策を尋ねるために`ask_user`を呼ぶ。先行する子Agent実行や`missing_information`は不要 | SC-02 | `POST /api/v1/agent-sessions`、`POST /api/v1/agent-sessions/{session_id}/turns` |
| 2 | システム | 質問カードを表示する | `clarification_request`が1件表示され、Turnは`completed`。投稿案と公開操作は表示されない | SC-02 | Turn送信のSSE |
| 3 | ユーザー | 対象施策を回答する | 元の質問Turn IDと回答の配列を同じ親Sessionの新しいTurnで受け付け、親Agentは回答を読んでコンテンツ制作へ進む | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |

**最終確認**

- 最初の質問Turnには`ask_user`があるが`run_content_creator`はない。親Agentだけの判断で成功する
- 質問カードの回答はX投稿の最終承認として扱わない

### E2E-015 投稿案の情報不足を質問カードで確認する

**事前条件**

- `MARKETER_A`でログイン済みで、未Archiveの対象Campaignがある
- Agent Fakeが`run_content_creator`から固定の`missing_information`を返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 対象Campaignの投稿案を依頼する | 子Agentから不足情報を受けた親Agentが`ask_user`で確認事項を提示し、投稿案は提示しない | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 2 | ユーザー | 質問カードに回答して送信する | 質問Turn IDと構造化した回答を既存のメッセージ送信APIへ渡して次のTurnを開始し、回答を踏まえた投稿案を返す | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |

**最終確認**

- 質問Turnは`completed`で`clarification_request`を持ち、`propose_x_post`は実行されない
- 回答Turnで再度`run_content_creator`を実行してから投稿案を表示し、Xへの公開は承認ボタンまで実行しない

### E2E-016 初期登録した責任者が管理画面とマーケター向け画面へログインする

**事前条件**

- 初期設定スクリプトへ大文字を含むメールアドレスを指定し、`COMPANY_A`と`ADMIN_A`を同一トランザクションに登録している。DBのEmailは前後空白を除去・小文字化した値で、`ADMIN_A`はactive、adminsと本人のmarketersを持つ
- `ADMIN_A`は未ログインである

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | 初期設定時のメールアドレスを小文字にして`/admin/login`からログインする | 管理者ログインが成功し、`/admin/users`へ移動する。`GET /auth/me`の`is_admin`はtrueである | SC-10、SC-11 | `GET /api/v1/auth/me`、`POST /api/v1/admin/auth/login` |
| 2 | `ADMIN_A` | 「チャット・施策へ」を選ぶ | 再ログインせず`/chat`を開き、本人の会話だけを表示する。「管理画面へ」ボタンが通常のナビとは別に表示される | SC-11、SC-02 | `GET /api/v1/auth/me`、`GET /api/v1/agent-sessions` |
| 3 | `ADMIN_A` | 「管理画面へ」を選ぶ | 同じCookieのまま`/admin/users`へ戻れる | SC-02、SC-11 | `GET /api/v1/admin/users?page=1` |
| 4 | `ADMIN_A` | ログアウトしてから`/login`でマーケター用ログインを試す | 共通Cookieと入口ヒントCookieが削除される。同じ本人でも管理ユーザーはマーケター用ログインAPIで認証されず、ユーザー種別を特定できない認証エラーになる | SC-01、SC-11 | `POST /api/v1/auth/logout`、`POST /api/v1/auth/login` |
| 5 | 開発者 | メールアドレスの大小文字と前後空白を変え、別会社名を指定して初期設定スクリプトを再実行する | 正規化後のメール重複で拒否され、別会社・責任者は作成されない | 画面なし | 初期設定スクリプト |

**最終確認**

- 会社に責任者が1人だけ存在し、会社・責任者ユーザー・admins・marketersが揃っている。初期登録では招待メールを送っていない
- 初期登録した責任者のメールアドレスは招待APIと同じ正規化済みで全社一意である。大小文字・前後空白だけ異なる再登録では会社も含めてロールバックされる
- 2種類の画面で共通Cookieが使われ、会話履歴の所有者は`ADMIN_A`本人の`marketer_id`である
- ログイン用と入口ヒント用のCookieが別物であり、後者は権限判定に使われない

### E2E-017 マーケターユーザーを招待し、本人が登録・ログインする

**事前条件**

- `ADMIN_A`がログイン済みで、`INVITEE_A`のメールアドレスは未使用である
- SES Fakeは招待メールを受け付け、リンクをテスト環境から取得できる

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | ユーザー一覧からマーケターユーザーを招待する | `201`が返り、種別・表示名・メールアドレスを持つ`invited`ユーザーが一覧へ表示される。SESの受付状態はacceptedである | SC-11 | `POST /api/v1/admin/users`、`GET /api/v1/admin/users?page=1` |
| 2 | `INVITEE_A` | SES Fakeのメールのリンクを開き、パスワード送信前に画面を再読み込みする | tokenクエリが残り、フォームを再表示できる。初期表示・再読み込みでリンク検証APIは呼ばれない | SC-12 | なし |
| 3 | `INVITEE_A` | 新しいパスワードを設定する | `POST`で本人の登録が完了し、ログイン画面へ履歴を置き換えて移動する。使用済みリンクは再使用できない | SC-12、SC-01 | `POST /api/v1/invitation-acceptances` |
| 4 | `INVITEE_A` | `/login`でログインする | マーケター向け画面を使え、管理画面へ移動するボタンはない | SC-01、SC-02 | `POST /api/v1/auth/login`、`GET /api/v1/auth/me` |

**最終確認**

- `INVITEE_A`のusersはactiveで、所属会社のmarketersを1件持ち、adminsは持たない。`COMPANY_A`には複数のmarketersが所属できる
- 招待行と送信操作はSES呼び出し前に存在し、リンクの有効期限は発行時刻から1時間である。パスワードハッシュとトークンの平文はAPI Responseにない

### E2E-018 管理ユーザーを招待し、本人が登録・管理画面を開く

**事前条件**

- `ADMIN_A`がログイン済みで、管理ユーザーに招待する`INVITEE_A`のメールアドレスは未使用である
- SES Fakeは招待メールを受け付ける

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | 種別を管理ユーザーとして招待する | 招待中の対象が一覧に表示され、管理ユーザー種別と表示名を確認できる | SC-11 | `POST /api/v1/admin/users`、`GET /api/v1/admin/users?page=1` |
| 2 | `INVITEE_A` | 招待リンクでパスワードを設定し、案内された`/admin/login`からログインする | 登録結果の種別はadminで、管理ユーザーログインが成功して`/admin/users`へ移動する | SC-12、SC-10、SC-11 | `POST /api/v1/invitation-acceptances`、`POST /api/v1/admin/auth/login` |
| 3 | `INVITEE_A` | マーケター向け画面へ移動する | 再ログインせず本人のマーケター向け機能を利用できる | SC-11、SC-02 | `GET /api/v1/auth/me`、`GET /api/v1/agent-sessions` |

**最終確認**

- 対象のusers・admins・marketersは同じ会社に属し、責任者フラグはfalseである
- 招待登録APIは認証Cookieを発行せず、パスワード設定後に管理者ログインAPIでCookieが発行される

### E2E-019 自社ユーザーの一覧・ページ移動・表示名編集を行う

**事前条件**

- `ADMIN_A`がログイン済みで、`COMPANY_A`に25人以上のユーザーがいる。招待中・利用中・停止中を含める

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | `/admin/users?page=1`を開く | 登録日時の新しい順で先頭20人と総件数・総ページ数を表示する。責任者・利用状態・直近のメール送信状態を確認できる | SC-11 | `GET /api/v1/admin/users?page=1` |
| 2 | `ADMIN_A` | ページネーションで次・前・最後・先頭を操作する | URLのpageと表示内容が同期し、現在ページと前後2ページを含む操作範囲が表示される | SC-11 | `GET /api/v1/admin/users?page=2`、`GET /api/v1/admin/users?page=1` |
| 3 | `ADMIN_A` | 招待中・停止中のユーザーの操作モーダルで表示名を編集する | 種別は読み取り専用で、確認モーダルを出さずに`200`で新しい表示名を反映する。メールアドレス・ユーザー種別・利用状態・認証世代は変わらない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |

**最終確認**

- 各ページが20件以内で、同じ作成日時の行はユーザーIDで順序が固定される
- 範囲外のpageは`400 INVALID_ARGUMENT`を受け、画面は`/admin/users?page=1`へ戻る

### E2E-020 利用中ユーザーを昇格・降格し、旧ログインと本人の会話履歴を確認する

**事前条件**

- `ADMIN_A`、`MARKETER_A`、責任者ではない`ADMIN_A2`が同じ`COMPANY_A`でactive。対象の2人は別々のBrowser Contextでログイン済みで、それぞれ本人の会話履歴を持つ

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | `MARKETER_A`の操作モーダルで表示名と種別を管理ユーザーへ変更し、確認モーダルを開いて一度キャンセルする | 変更前後の種別と旧ログインの失効を示す。下のモーダルは操作できず、キャンセル後も入力内容が残る。PATCHはまだ送られない | SC-11 | なし |
| 2 | `ADMIN_A` | 再度確認し、昇格を確定する | 表示名と種別を1回のPATCHで更新し、`200`の`data.user`を一覧に反映する。`admins`を追加して認証世代を1回更新する。本人の`marketers`・パスワード・会話履歴は変わらず、SES送信と`emails`・`invitations`の変更もない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |
| 3 | `MARKETER_A` | 昇格前のCookieで認証付き画面を再読み込みし、既存のリンクから管理者ログインへ移って再ログインする | 旧Cookieは`401 UNAUTHENTICATED`。管理者ログイン成功後にユーザー管理と本人の会話履歴を利用できる。他人の会話履歴は見られない | SC-01、SC-10、SC-11、SC-02 | `GET /api/v1/auth/me`、`POST /api/v1/admin/auth/login`、`GET /api/v1/agent-sessions` |
| 4 | `ADMIN_A` | `ADMIN_A2`の種別だけをマーケターユーザーに変更し、確認して確定する | 1回のPATCHで`admins`を削除し認証世代を1回更新する。表示名・`marketers`・会話履歴・パスワードは維持され、メールは送信されない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |
| 5 | `ADMIN_A2` | 降格前のCookieで管理画面を再読み込みし、既存のリンクからマーケター用ログインへ移って再ログインする | 旧Cookieは`401 UNAUTHENTICATED`。管理者ログインは拒否され、マーケター用ログインが成功し本人の会話履歴を開ける。管理画面・管理APIは利用できない | SC-11、SC-10、SC-01、SC-02 | `GET /api/v1/auth/me`、`POST /api/v1/admin/auth/login`、`POST /api/v1/auth/login`、`GET /api/v1/admin/users?page=1` |

**最終確認**

- 両方向とも同じユーザーID・marketer_idで会話履歴を保持し、変更前のCookieは新種別でのログイン後も復活しない
- 招待メールは送られず、招待・送信履歴は増減しない

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

### E2E-E07 質問への回答Turnが失敗しても修正して再回答できる

**事前条件**

- `MARKETER_A`が完了済みの質問Turnと未回答の質問カードを持つ
- Agent Fakeは最初の回答Turnで実行エラーを返し、次の回答Turnでは成功する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | ユーザー | 質問Turn IDと回答配列を送信する | 回答`user_message`は保存されるがAgentの実行は`failed`で終了し、エラーが表示される。再読み込みなしで質問カードは`answered = false`のままになる | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 2 | ユーザー | 画面を再読み込みする | 失敗Turnと回答は履歴に残るが、質問カードの`answered = false`で再回答可能。失敗時の回答を入力欄に復元できる | SC-02 | `GET /api/v1/agent-sessions/{session_id}` |
| 3 | ユーザー | 回答を修正して同じ質問Turn IDで再送する | `CLARIFICATION_ALREADY_ANSWERED`にならず、新しい回答Turnが作成される。失敗Turnの内容は新しいAgent Contextへ混入しない | SC-02 | `POST /api/v1/agent-sessions/{session_id}/turns` |
| 4 | システム | 再回答のTurnを完了する | 親Agentが新しい回答から処理を続け、`turn_finished`直後に質問カードの`answered`が`true`になり、再読み込みしなくても回答Buttonが消える | SC-02 | Turn送信のSSE |

**最終確認**

- 同じ質問Turnへ失敗した回答Turnと完了した回答Turnが各1件あり、完了した回答Turnだけが回答済み判定と次の会話Contextに使われる
- 完了後に同じ質問Turnへ再回答すると`409 CLARIFICATION_ALREADY_ANSWERED`となり、新しいTurnは作られない
- 隔離済みの回答Itemを持つ`completed` Turnのケースは別Fixtureで確認する。`clarification_request.answered`は`false`で、同じ質問Turnへ修正した回答を新しいTurnとして送れる。隔離済みItemの内容は表示とAgent Contextの回答に使用しない

### E2E-E08 利用停止・再開で旧ログインとリンクを失効させる

**事前条件**

- `ADMIN_A`と`ADMIN_A2`でログイン済みで、同じ会社の`MARKETER_A`はactiveでログイン済み。別の`INVITEE_A`はinvitedで未使用リンクを持つ

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | `MARKETER_A`の操作モーダルから停止し、重ねた確認モーダルで確定する | ユーザーがsuspendedとなり、パスワードハッシュが消去され、認証世代が更新される | SC-11 | `POST /api/v1/admin/users/{user_id}/suspensions` |
| 2 | `MARKETER_A` | 停止前のCookieで画面を再読み込みする | `401 UNAUTHENTICATED`となり、本人の業務画面を表示しない | SC-01、SC-02 | `GET /api/v1/auth/me` |
| 3 | `ADMIN_A` | 停止済みの`MARKETER_A`を利用再開し、送信を確認する | invitedに戻るが、旧パスワードではログインできない。新しいリンクと送信操作が作られる | SC-11 | `POST /api/v1/admin/users/{user_id}/reactivations` |
| 4 | `ADMIN_A` | Browserから同じ利用再開Requestを再送する | `200`で現在の状態を返し、SES Fakeの呼び出し回数・招待行・認証世代は変わらない | SC-11 | `POST /api/v1/admin/users/{user_id}/reactivations` |
| 5 | `MARKETER_A` | 新しいリンクからパスワードを設定してログインする | activeになり、以前のCookieは再開後も無効。既存の本人の会話履歴は保持される | SC-12、SC-01、SC-02 | `POST /api/v1/invitation-acceptances`、`POST /api/v1/auth/login` |
| 6 | `ADMIN_A` | 招待中の`INVITEE_A`を停止してから、旧リンクでパスワード設定を試す | 同じ`400 INVITATION_LINK_INVALID`で拒否され、登録できない | SC-11、SC-12 | `POST /api/v1/admin/users/{user_id}/suspensions`、`POST /api/v1/invitation-acceptances` |
| 7 | `ADMIN_A2` | 自分自身と責任者`ADMIN_A`への停止を試す | UIでは停止を選べない。APIへ直接Requestしても`409 USER_SUSPENSION_FORBIDDEN`となり、状態は変わらない | SC-11 | `POST /api/v1/admin/users/{user_id}/suspensions` |

**最終確認**

- 招待中と登録済みのどちらも停止できるが、停止・再開前のCookieとリンクは復活しない
- 管理ユーザー本人と責任者は画面で停止できず、APIからの試行も`409 USER_SUSPENSION_FORBIDDEN`で拒否される

### E2E-E09 招待リンクの期限切れ・再送・一度きりの使用を確認する

**事前条件**

- `ADMIN_A`がログイン済み。`INVITEE_A`はinvitedで、発行時刻を固定したリンクを持つ
- Clockを発行から1時間以上進められる

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `INVITEE_A` | 期限切れリンクでパスワード設定を試す | `400 INVITATION_LINK_INVALID`となり、利用可能なアカウントにならない | SC-12 | `POST /api/v1/invitation-acceptances` |
| 2 | `ADMIN_A` | 招待中の対象を開き、再送を確認・確定する | 古いリンクを無効化して新しいリンクをSESへ送り、送信受付結果を一覧に表示する | SC-11 | `POST /api/v1/admin/users/{user_id}/invitations` |
| 3 | `INVITEE_A` | 新しいリンクからパスワードを設定し、同じリンクをもう一度使用する | 最初は登録でき、2回目はStep 1と同じエラー。登録後は再送操作を使用できない | SC-12、SC-11 | `POST /api/v1/invitation-acceptances` |
| 4 | `ADMIN_A` | 利用中となった`INVITEE_A`への招待メール再送をBrowserから試す | `409 USER_STATE_CONFLICT`となり、新しいメールとリンクを作らない | SC-11 | `POST /api/v1/admin/users/{user_id}/invitations` |

**最終確認**

- リンクの期限は発行時刻から1時間であり、再送のたびに古いリンクは無効になる。古いリンクは送信結果にかかわらず復活しない
- トークンはハッシュだけ保存され、パスワード保存・リンク使用済み化・active化は同一トランザクションで行われる

### E2E-E10 管理権限・他社ユーザー・他人の会話履歴の境界を確認する

**事前条件**

- `MARKETER_A`、`ADMIN_A`、`ADMIN_B`のログイン情報をFixtureで用意する
- `ADMIN_A2`と、`MARKETER_A`の親Sessionを`COMPANY_A`に用意する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `MARKETER_A` | 管理画面のURLを開き、管理APIへアクセスする | ユーザー情報を表示しない。管理APIは`403 ADMIN_FORBIDDEN`を返す | SC-11 | `GET /api/v1/admin/users?page=1` |
| 2 | `ADMIN_A` | 有効な表示名Bodyを使い、`COMPANY_B`のユーザーIDと存在しないIDへの操作を確認する | どちらも`404 ADMIN_USER_NOT_FOUND`で同じ応答となり、他社の状態を表示・変更しない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |
| 3 | `ADMIN_A` | 同じ会社の他人の会話URLを開く | 本人が所有しないSessionは`404 AGENT_SESSION_NOT_FOUND`となり、管理ユーザーでも閲覧できない | SC-02 | `GET /api/v1/agent-sessions/{session_id}` |
| 4 | `ADMIN_A` | 既存の自社・他社ユーザーのメールアドレスについて大小文字・前後空白を変えて招待を試す | 正規化後はいずれも`409 USER_INVITATION_CONFLICT`と同じ説明で拒否され、登録先の会社を推測できない | SC-11 | `POST /api/v1/admin/users` |

**最終確認**

- 他社のデータと本人以外の会話履歴を取得・変更できない。メールアドレス重複による招待競合は自社・他社を区別せず`409 USER_INVITATION_CONFLICT`となる
- 管理画面の表示制御だけでなくAPIでも管理権限・会社境界を検証している

### E2E-E11 SESの明確な失敗とスロットリング再試行を区別する

**事前条件**

- `ADMIN_A`がログイン済み。SES Fakeはスロットリング応答を2回返した後に受付成功するモードと、明確な失敗を返すモードへ切り替えられる

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | 1人目を招待する | 同じリンクで初回を含め最大3回呼び出し、最後に`201`と受付成功を表示する | SC-11 | `POST /api/v1/admin/users` |
| 2 | `ADMIN_A` | 2人目を招待してSES Fakeから明確な失敗を受け取る | `502 INVITATION_SEND_FAILED`を表示し、ユーザーを招待中のまま一覧に残す | SC-11 | `POST /api/v1/admin/users`、`GET /api/v1/admin/users?page=1` |
| 3 | `ADMIN_A` | SES Fakeを受付成功に切り替え、失敗した対象の招待メールを手動再送する | 古いリンクを無効化し、新しいリンクと送信操作が作られる。再送は管理ユーザーの明示操作でだけ行われる | SC-11 | `POST /api/v1/admin/users/{user_id}/invitations` |

**最終確認**

- SES Fakeの送信回数と`emails.attempt_count`が一致する。自動リトライでは同じリンクを使い、待機は指数バックオフとジッターの方針に従う
- 失敗したメールでも`users`・`emails`・`invitations`は送信前に作成済みで、手動再送までは旧リンクが有効である

### E2E-E12 SESの結果不明で自動再送せず、管理者が手動再送する

**事前条件**

- `ADMIN_A`がログイン済み。SES Fakeは5xx、408、応答なし、処理中断を各ケースで再現できる
- 上記の結果不明の原因ごとに、独立したFixture・Browser ContextでStepを繰り返す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A` | 招待を実行し、SES Fakeで結果不明を発生させる | `504 INVITATION_SEND_OUTCOME_UNKNOWN`または処理中断として「送信結果を確認できませんでした」を表示し、自動再送しない | SC-11 | `POST /api/v1/admin/users` |
| 2 | `ADMIN_A` | 一覧を開き直す | 招待中ユーザーとリンクが残り、送信結果不明を送信失敗と区別する。中断して`pending`のままでも時間経過で自動遷移しない | SC-11 | `GET /api/v1/admin/users?page=1` |
| 3 | `ADMIN_A` | 手動再送を確定する | 古いリンクを無効化し、新しいリンクを含むメールを送信する | SC-11 | `POST /api/v1/admin/users/{user_id}/invitations` |

**最終確認**

- 結果不明になった元の送信操作へのSES Fake呼び出しは1回だけで、SDK側の自動リトライも行わない
- 結果不明のリンクは手動再送まで有効であり、手動再送後は古い送信の受付結果が遅れて判明しても再び有効にならない

### E2E-E13 管理ユーザーの認証切れ後に管理者ログインへ戻る

**事前条件**

- `ADMIN_A`が`/admin/login`からログインしてマーケター向け画面を開いている
- 認証Cookieを期限切れにできる。入口ヒントCookieは残す

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | テスト環境 | 認証Cookieだけを期限切れにする | `hiromeru_login_portal=admin`は残り、認証には使用されない | SC-02 | なし |
| 2 | `ADMIN_A` | マーケター向け画面を再読み込みする | 管理者ログイン画面へ移動し、元のURLが安全な`next`として保持される | SC-02、SC-10 | `GET /api/v1/auth/me` |
| 3 | `ADMIN_A` | 再ログイン後に明示的にログアウトする | 本人の画面へ戻れる。ログアウトで認証Cookie・CSRF Token・入口ヒントCookieが削除される | SC-10、SC-02 | `POST /api/v1/admin/auth/login`、`POST /api/v1/auth/logout` |

**最終確認**

- 入口ヒントCookieがない場合は`/login`を既定にする。両ログイン画面には互いへの移動リンクがある
- 入口ヒントCookieの値を書き換えても、管理APIの認可は変わらない

### E2E-E14 禁止対象の種別変更と同時編集の競合を拒否する

**事前条件**

- `ADMIN_A2`・`ADMIN_A`・`ADMIN_B`・`MARKETER_A2`が別々のBrowser Contextでログイン済み。`ADMIN_A`は同じ会社の責任者で、`MARKETER_A`はactive。別の招待中ユーザーと停止中ユーザーを同じ会社に用意する

| Step | 操作者 | 操作 | 確認項目 | 関連画面 | 関連API |
| ---: | --- | --- | --- | --- | --- |
| 1 | `ADMIN_A2` | 自分自身・責任者・招待中・停止中の操作モーダルを開く | 種別は読み取り専用で表示され、表示名は編集できる | SC-11 | `GET /api/v1/admin/users?page=1` |
| 2 | `ADMIN_A2` | 自分自身と責任者の種別変更を、認証済みBrowser ContextからAPIで試す | いずれも`409 USER_ROLE_CHANGE_FORBIDDEN`。表示名・種別・認証世代は変わらない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |
| 3 | `ADMIN_A2` | 招待中・停止中のユーザーに新しい表示名と異なる種別を同時に指定し、APIで変更を試す | いずれも`409 USER_STATE_CONFLICT`。表示名も含めて部分更新されず、認証世代も変わらない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |
| 4 | `ADMIN_A2`・`ADMIN_A` | `ADMIN_A2`が`MARKETER_A`の表示名と種別を入力して確認モーダルを開き、`ADMIN_A`が別Browser Contextから対象を停止する。その後`ADMIN_A2`が確定する | `409 USER_STATE_CONFLICT`。表示名も種別も変更されず、一覧の再取得後は種別が読み取り専用になる | SC-11 | `POST /api/v1/admin/users/{user_id}/suspensions`、`PATCH /api/v1/admin/users/{user_id}`、`GET /api/v1/admin/users?page=1` |
| 5 | `ADMIN_A2` | 停止中ユーザーに表示名と現在と同じ種別を指定してAPIで更新する | 種別が実際には変わらないため`200`。表示名のみ更新され、認証世代更新・メール送信はない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |
| 6 | `ADMIN_A2`・`ADMIN_B`・`MARKETER_A2` | `ADMIN_A2`が他社ユーザーと存在しないID、`ADMIN_B`が`COMPANY_A`のユーザー、`MARKETER_A2`が管理APIへの種別変更を試す | 他社・存在しないIDはいずれも`404 ADMIN_USER_NOT_FOUND`で区別できず、管理権限なしは`403 ADMIN_FORBIDDEN`。どのユーザーも変更されない | SC-11 | `PATCH /api/v1/admin/users/{user_id}` |

**最終確認**

- 種別変更の条件とエラーは表示制御だけでなくAPIでも適用し、同時編集の失敗では部分更新しない
- 他社ユーザーの種別変更は存在しないユーザーと同じ`404 ADMIN_USER_NOT_FOUND`、管理権限のないユーザーからの種別変更は`403 ADMIN_FORBIDDEN`となる

## 10. 手動動作確認

自動E2Eと同じ業務結果を再確認するのではなく、視覚、操作感、支援技術、実行環境に依存する項目を確認する。

### 10.1 共通UI

| ID | 操作 | 確認項目 | 対象画面 |
| --- | --- | --- | --- |
| MAN-001 | Desktop、Tablet、320px幅で主要フローを表示する | 内容の欠落、重なり、意図しない横Scrollがない | SC-01、SC-02、SC-04からSC-12 |
| MAN-002 | Browserを200%へZoomする | 入力、主要操作、Error、Navigationへ到達できる | 全画面 |
| MAN-003 | Mouseを使わずTab、Shift+Tab、Enter、Space、Escapeで操作する | Focus順、Focus表示、Dialog、Form送信、Navigationが適切である | 全画面 |
| MAN-004 | Loading、Empty、Error、Not Foundを順に表示する | 状態の意味と次の操作が視覚的かつ文言で分かる | 全画面 |
| MAN-005 | 長い会話、施策、投稿、Error文を表示する | 省略規則が一貫し、必要な全文へ到達でき、Layoutが崩れない | SC-01、SC-02、SC-04からSC-12 |
| MAN-006 | `prefers-reduced-motion: reduce`で操作する | 不要なAnimationが抑制され、状態変化は認識できる | 全画面 |

### 10.2 FormとAgent操作

| ID | 操作 | 確認項目 | 対象画面 |
| --- | --- | --- | --- |
| MAN-007 | 必須入力を空にして送信する | Errorが入力と関連付けられ、最初のErrorへFocusが移る | SC-01、SC-02、SC-05、SC-10からSC-12 |
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
| MAN-022 | 招待・ユーザー操作モーダルから確認モーダルを重ねて開閉する | 最上位だけ操作でき、キャンセル時は起点の操作へFocusが戻り種別変更中の表示名・種別入力は残る。変更できない対象の種別は読み取り専用で分かり、送信中と結果不明を色だけで区別しない | SC-11 |
| MAN-023 | 招待リンクと認証状態をBrowser Network・Logで確認する | 招待画面ではパスワード設定完了までtokenクエリを保持し、登録APIではBodyだけに含める。画面応答は`Referrer-Policy: no-referrer`と`Cache-Control: no-store`を持ち、後続RequestのRefererへトークンを付けない。初回アクセスのクエリをアクセスログでマスクし、トークン・パスワード・Cookieをアプリケーションログへ残さない。登録完了後は履歴を置き換えてトークン付き画面を復元しない | SC-10からSC-12、Browser Network、Backend Log |

## 11. 合否基準

### 11.1 テストケース

- 全Stepの操作を実行でき、確認項目をすべて満たすこと
- 最終確認のUI、API、永続化、外部作用がすべて一致すること
- 想定外のBrowser Console Error、未処理例外、5xxがないこと。SESの明確な失敗`502`、送信結果不明`504`など、異常系ケースで期待される応答は除く
- ケース終了後に未完了のTurn、Lease、処理中の冪等性レコードが残らないこと。ただし、結果不明を確認するE2E-E06は除く

### 11.2 リリース判定

- 優先度「必須」の自動E2Eがすべて成功すること
- 手動動作確認で操作不能、情報漏洩、外部への意図しない副作用がないこと
- 失敗を既知問題として許容する場合は、対象ケース、利用者影響、回避策、Issueを記録すること

## 12. 実装状況

本書はv0.1の完成形を対象とする。実行対象の機能とE2E Runnerがそろったケースから検証する。実装状況はケース単位で管理する。

E2E Runner、起動Command、Fixtureの配置、Artifactの保存先は、テスト基盤の採用時に本節へ追記する。
