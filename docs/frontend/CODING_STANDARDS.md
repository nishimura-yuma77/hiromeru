# Frontendコーディング規約

## 1. 目的

本書は、HiromeruのFrontendを一貫した構造と責務で実装するための規約を定義する。

Frontendは、ユーザー操作の表示と入力を担当する。業務ルール、サーバーデータ、画面状態を混在させず、変更理由が異なるコードを分離する。

本書では規約の強さを次のように表す。

| 表記     | 意味                                                                         |
| -------- | ---------------------------------------------------------------------------- |
| **必須** | 原則として例外を認めない。例外が必要な場合はPull Requestへ理由を記載する     |
| **推奨** | 特別な理由がなければ従う。採用しない場合は実装上の理由を説明できるようにする |
| **任意** | 状況に応じて選択できる                                                       |

実装判断の優先順位は、`プロダクト要件 > 本書 > グローバルSkill`とする。Skillの内容は本書へ明示的に取り込んだ時点でプロジェクト規約となり、Skillの更新だけで本書の規約は変更されない。

## 2. 適用範囲

本書は`frontend/`配下のNext.js、React、TypeScript、SCSSおよびFrontendテストへ適用する。

APIの仕様、業務ルール、Agentの動作は次の設計書を正本とする。

- `docs/v.0.1/REQUIREMENTS.md`
- `docs/v.0.1/USECASE.md`
- `docs/v.0.1/API_DESIGN.md`
- `docs/v.0.1/AGENT_DESIGN.md`

## 3. 技術スタック

| 用途         | 技術                                       |
| ------------ | ------------------------------------------ |
| Framework    | Next.js App Router                         |
| UI           | React                                      |
| 言語         | TypeScript strict mode                     |
| Server read  | React Server Components                    |
| Client state | React `useReducer`                         |
| Style        | SCSS Modules                               |
| 静的解析     | ESLint、eslint-config-next Core Web Vitals |

新しいライブラリは、既存の技術で要件を満たせないことを確認してから追加する。

## 4. ディレクトリ構成

```text
frontend/
├── app/
│   ├── layout.tsx
│   ├── layout.module.scss
│   ├── page.tsx
│   ├── page.module.scss
│   ├── loading.tsx
│   ├── loading.module.scss
│   ├── error.tsx
│   ├── error.module.scss
│   ├── not-found.tsx
│   └── not-found.module.scss
│
├── features/
│   └── campaigns/
│       ├── components/
│       │   └── CampaignView/
│       │       ├── CampaignView.tsx
│       │       └── CampaignView.module.scss
│       ├── containers/
│       │   └── CampaignEditor.tsx
│       ├── controllers/
│       │   ├── useCampaignFormController.ts
│       │   └── useCampaignApprovalController.ts
│       ├── state/
│       │   ├── campaignFormReducer.ts
│       │   ├── campaignEvents.ts
│       │   └── campaignSelectors.ts
│       ├── api/
│       │   └── campaignClient.ts
│       ├── server/
│       │   ├── getCampaign.ts
│       │   └── listCampaigns.ts
│       ├── types/
│       │   ├── campaign.ts
│       │   └── CampaignViewModel.ts
│       └── utils/
│           └── campaignUtils.ts
│
├── shared/
│   ├── components/
│   │   └── Button/
│   │       ├── Button.tsx
│   │       └── Button.module.scss
│   ├── api/
│   │   ├── browserApiClient.ts
│   │   ├── serverApiClient.ts
│   │   └── ApiError.ts
│   ├── hooks/
│   ├── lib/
│   ├── styles/
│   │   ├── _tokens.scss
│   │   ├── _breakpoints.scss
│   │   ├── _mixins.scss
│   │   └── globals.scss
│   └── types/
│
├── public/
├── eslint.config.mjs
├── next-env.d.ts
├── next.config.ts
├── package.json
├── package-lock.json
└── tsconfig.json
```

実際のFeature名は業務上の機能単位とする。`agent`、`campaigns`、`posts`など、利用者が認識する機能を基準に分割する。

### 4.1 `app/`

`app/`はNext.jsのルーティング、Layout、PageおよびFeatureの組み立てだけを担当する。

- **必須:** 業務ロジックを記述しない
- **必須:** `fetch`を直接実行せず、Featureの型付けされたServer関数を呼び出す
- **必須:** Featureのcontrollerと純粋UIを接続する
- **推奨:** Pageを薄く保ち、処理をFeatureへ委譲する

### 4.2 `features/`

`features/`は機能固有のUI、状態、API、型、controllerおよびロジックを保持する。

- `components/`: 純粋な表示コンポーネント
- `containers/`: Server Props、責務別controller、純粋UIを接続するClient境界
- `controllers/`: Client Event、Reducer、API更新処理とUIの接続
- `state/`: Reducer、Event、Selector
- `api/`: Browserから実行する型付けされたAPI更新関数
- `server/`: Server Componentから呼び出す型付けされた読取関数
- `types/`: Feature固有の型とViewModel
- `utils/`: Feature固有の純粋関数

### 4.3 `shared/`

`shared/`は複数Featureで利用する共通コードを保持する。

- **必須:** 特定Featureの業務知識を持たせない
- **必須:** 再利用される見込みだけでコードを移動しない
- **推奨:** 2つ以上のFeatureで同じ責務が必要になった時点で共通化を検討する

### 4.4 依存方向

依存方向は次に限定する。

```text
app ──────> features ──────> shared
 └────────────────────────> shared
```

- **必須:** `shared`から`features`を参照しない
- **必須:** `shared`から`app`を参照しない
- **必須:** `features`から`app`を参照しない
- **必須:** Feature間の直接参照を原則禁止する
- **推奨:** 複数Featureで本当に共通する処理だけを`shared`へ移動する

## 5. 命名規則

| 対象                | 規則                           | 例                          |
| ------------------- | ------------------------------ | --------------------------- |
| React Component     | PascalCase                     | `CampaignForm`              |
| Component directory | PascalCase                     | `CampaignForm/`             |
| Component file      | PascalCase                     | `CampaignForm.tsx`          |
| SCSS Module         | Componentと同名                | `CampaignForm.module.scss`  |
| Hook                | `use` + PascalCase             | `useCampaignFormController` |
| 関数・変数          | camelCase                      | `createCampaign`            |
| 型                  | PascalCase                     | `CampaignViewModel`         |
| 定数                | UPPER_SNAKE_CASE               | `DEFAULT_PAGE_SIZE`         |
| SCSS class          | camelCase                      | `.submitButton`             |
| Feature directory   | kebab-caseまたは小文字の業務名 | `campaigns/`                |

- **必須:** bool値は状態を判別できる名前にする。`isPending`、`hasError`、`canSubmit`などを使用する
- **必須:** `data`、`item`、`value`など、文脈が分からない名前を広いスコープで使用しない
- **推奨:** Event名はユーザー操作または発生済みの事実として命名する

## 6. Component規約

### 6.1 ファイル構成

見た目を持つComponentは、Component単位のディレクトリへ配置する。

```text
CampaignForm/
├── CampaignForm.tsx
└── CampaignForm.module.scss
```

- **必須:** 見た目を持つComponentごとに同名の`*.module.scss`を1つ作成する
- **必須:** Component固有のStyleを別ComponentのSCSSへ記述しない
- **必須:** Provider、controller hook、Server関数、型定義など、見た目を持たない処理にはSCSSを作成しない

### 6.2 純粋UI

UI Componentは、Propsに対応する表示とユーザーEventの通知だけを担当する。

- **必須:** ドメインロジックを持たない
- **必須:** API関数を直接呼び出さない
- **必須:** router、storage、時刻、UUIDなどの外部要因へ直接依存しない
- **必須:** 表示に必要な値をViewModelとして受け取る
- **必須:** ユーザー操作をEventまたはcallbackでcontrollerへ通知する
- **推奨:** 同じPropsに対して同じ出力を返すComponentにする

```tsx
type CampaignViewProps = {
  viewModel: CampaignViewModel;
  onEvent: (event: CampaignEvent) => void;
};

export function CampaignView({ viewModel, onEvent }: CampaignViewProps) {
  return (
    <form>
      <input
        aria-label="施策タイトル"
        value={viewModel.title}
        onChange={(event) =>
          onEvent({
            type: "fieldChanged",
            field: "title",
            value: event.currentTarget.value,
          })
        }
      />
    </form>
  );
}
```

## 7. Server ComponentとClient Component

- **必須:** Server Componentをデフォルトとする
- **必須:** state、Event Handler、browser APIが必要な境界だけに`"use client"`を指定する
- **必須:** Server専用のSecretや認証情報をClient Componentへ渡さない
- **推奨:** Client Componentの境界を小さく保つ
- **推奨:** Server Componentから純粋UIへserializableなPropsだけを渡す

controller hookを実行する`containers/`の接続ComponentはClient Componentになる。Pageと表示だけを担当する子Componentまで不要にClient境界を広げない。

## 8. TypeScript規約

- **必須:** `strict`を有効にする
- **必須:** `any`を使用しない
- **必須:** 外部入力は`unknown`として受け取り、安全に型を絞り込む
- **必須:** APIのRequestとResponseに型を定義する
- **必須:** `null`と`undefined`の意味を区別する
- **必須:** 型アサーションで入力検証を回避しない
- **必須:** Exhaustive checkによりEventの処理漏れを検出する
- **推奨:** objectの型には`type`を基本として使用する
- **推奨:** Importには`@/` aliasを使用し、深い相対Pathを避ける

```ts
function assertNever(value: never): never {
  throw new Error(`Unhandled event: ${JSON.stringify(value)}`);
}
```

## 9. 状態管理

### 9.1 状態の分類

状態を保存場所と更新主体で分類する。

| 状態                              | 管理方法                                      |
| --------------------------------- | --------------------------------------------- |
| 読取専用のサーバーデータ          | Server Component                              |
| 編集中のForm snapshot             | Reactの`useReducer`                           |
| Clientからの更新操作              | 責務別controllerと型付けされたAPI client      |
| 更新処理のpending、success、error | Reactの`useReducer`                           |
| 派生状態                          | 純粋なSelector関数                            |
| 低レベルUI状態                    | 必要な場合だけ`useState`                      |
| 復元・共有される画面状態          | URL、Path Params、Search Params               |

- **必須:** 読取専用のサーバーデータをReducerへ複製しない
- **必須:** 編集対象のサーバーデータをReducerへ初期化する場合は、編集用snapshotであることを型と責務で明示する
- **必須:** Feature状態を`useState`で個別管理しない
- **必須:** 派生値をstateとして保存しない
- **必須:** Serverから渡されたPropsを`useEffect`でReducerへ同期しない
- **推奨:** Server再取得後に編集用snapshotを置き換える場合は、Componentの`key`または明示的なEventを使用する
- **推奨:** 低レベルUI部品の開閉、focus補助など、業務上の意味を持たない局所状態だけに`useState`を許可する

### 9.2 ReducerとEvent

Feature状態は、ひとつの責務単位で`useReducer`を使用して管理する。状態遷移はすべて明示的なEventで表現する。

```ts
type CampaignState = {
  form: CampaignFormValue;
  idempotencyKey: string | null;
};

type CampaignEvent =
  | {
      type: "fieldChanged";
      field: keyof CampaignFormValue;
      value: string;
    }
  | {
      type: "approvalStarted";
      idempotencyKey: string;
    }
  | {
      type: "approvalReset";
    };
```

- **必須:** Reducerを純粋関数にする
- **必須:** Stateを直接変更せず、新しいStateを返す
- **必須:** Reducer内でAPI、時刻取得、UUID生成、browser APIを実行しない
- **必須:** Eventをdiscriminated unionとして定義する
- **必須:** `default`で未処理Eventを黙って無視しない
- **必須:** ひとつのReducerへ無関係な責務を集約しない
- **推奨:** State、Event、Reducer、Selectorを別ファイルへ分離する

UUID、現在時刻などの外部値はcontrollerで生成し、EventのpayloadとしてReducerへ渡す。

### 9.3 Selector

Stateから計算できる値はSelectorとして定義する。

```ts
export function selectCanApprove(state: CampaignState): boolean {
  return state.form.title.trim().length > 0 && state.idempotencyKey === null;
}
```

- **必須:** Selectorを純粋関数にする
- **必須:** Selector内でStateを変更しない
- **推奨:** 複数箇所で使用する派生条件をSelectorへ集約する

### 9.4 URL state

再読込後の復元、共有、履歴移動、Deep linkを利用者が期待する状態はURLへ保持する。

URLへ保持する候補:

- 検索条件、Filter、Sort
- Tab、Pagination
- 選択中Record
- Deep linkが必要なPanelやAccordion

- **必須:** Path ParamsとSearch Paramsを使用前にparse、validateする
- **必須:** 不正値は安全なDefaultへ戻し、Errorや意図しないRequestを発生させない
- **必須:** Navigation履歴として残す変更には`router.push`、同一操作中の一時的な絞り込みには`router.replace`を使用する
- **必須:** Secret、個人情報、未確定のForm入力、Domain stateをURLへ保存しない
- **必須:** URL更新を`useEffect`で行わず、該当するEvent Handlerから行う
- **推奨:** Component stateを追加する前に、復元または共有すべきURL stateかを検討する

## 10. Controller規約

controllerは、Reducer、Client Event、API更新処理、router、browser APIと純粋UIの境界を担当する。1つのcontrollerは1つの操作責務だけを持つ。

PageはServer Componentとしてデータを取得し、Client境界のComponentへ必要なPropsだけを渡す。Client境界が責務別controllerを呼び出し、ViewModelとEvent Handlerを純粋UIへPropsで渡す。

```tsx
// app/campaigns/page.tsx
export default async function CampaignPage() {
  const campaign = await getCampaign();

  return (
    <CampaignEditor
      key={campaign.updatedAt}
      initialCampaign={toCampaignFormValue(campaign)}
    />
  );
}
```

```tsx
// features/campaigns/containers/CampaignEditor.tsx
"use client";

function CampaignEditor({ initialCampaign }: CampaignEditorProps) {
  const formController = useCampaignFormController(initialCampaign);
  const approvalController = useCampaignApprovalController({
    form: formController.viewModel.form,
  });

  return (
    <CampaignView
      form={formController.viewModel}
      approval={approvalController.viewModel}
      onFormEvent={formController.onEvent}
      onApprovalEvent={approvalController.onEvent}
    />
  );
}
```

- **必須:** `useXxxController`形式のCustom Hookとして定義する
- **必須:** Form編集、承認、検索など、独立して変更する責務ごとにcontrollerを分割する
- **必須:** ReducerのStateを画面表示用ViewModelへ変換する
- **必須:** 更新処理のpending、success、errorを対応するReducer Eventへ変換する
- **必須:** UIから受け取ったEventをReducerまたは型付けされたAPI clientへ振り分ける
- **必須:** API Errorを利用者向けの表示状態へ変換する
- **必須:** Idempotency-Keyの生成と再利用を制御する
- **必須:** 無関係なStateと操作を1つのViewModelへ集約しない
- **推奨:** UIへ`dispatch`を直接公開せず、FeatureのEvent Handlerとして公開する
- **推奨:** HookとPropsを基本とし、深いProps drillingが具体的な問題になった場合だけContextを検討する
- **推奨:** Event Handlerの参照同一性が必要なのは、memo化された境界など具体的な理由がある場合に限る

controllerは業務ルールの正本にならない。入力の最終検証、認可、所有権、冪等性の保証はBackendが担当する。

## 11. サーバー通信規約

### 11.1 Server Componentでの読取

初期表示、SEO対象、画面表示に必要な通常の読取はServer Componentで実行する。

- **必須:** `app/`からraw `fetch`を実行せず、`features/<feature>/server`の型付けされた関数を呼び出す
- **必須:** Server専用関数へ`server-only`を指定し、Client bundleへの混入を防ぐ
- **必須:** 独立したRequestは同時に開始し、`Promise.all`などで並列に待機する
- **必須:** Client Componentへ渡すPropsを表示と操作に必要な最小限へ絞る
- **必須:** API Response全体や同じ意味の重複PropsをClientへ渡さない
- **推奨:** 遅い部分をSuspense境界で分離し、画面全体の表示を不必要に待たせない
- **推奨:** Request内の重複読取はReact `cache`などでdeduplicateする

### 11.2 Clientからの更新

状態変更APIは、責務別controllerのEvent Handlerから`features/<feature>/api`の型付けされた関数を呼び出す。

- **必須:** 更新開始、成功、失敗を明示的なReducer Eventとして扱う
- **必須:** 状態変更Requestを暗黙に自動再試行しない
- **必須:** Backendが`CSRF_VALIDATION_FAILED`を返した場合だけ、CSRF Token再発行後に元Requestを1回再送する。承認Requestは同じ`Idempotency-Key`を維持し、2回目のCSRF Errorでは停止する
- **必須:** 更新中は同じ操作の重複実行を防ぐ
- **必須:** 更新成功後は必要に応じて`router.refresh()`し、Server Componentの表示を再取得する
- **必須:** API Errorを共通の`ApiError`へ正規化する
- **必須:** Idempotency-Keyが必要な更新では、同じ承認操作の再送に同じKeyを使用する

### 11.3 Client側の再取得

検索候補、PollingなどClient側の再取得が必要な場合だけ個別実装を許可する。

- **必須:** Server Componentで実現できない理由をPull Requestへ記載する
- **必須:** 責務別controllerまたは専用Hookへ閉じ込め、UI Componentから直接Requestしない
- **必須:** `AbortSignal`を使用し、古いRequestを中断できるようにする
- **必須:** 検索Requestは入力Eventから開始し、必要に応じてdebounceする
- **必須:** PollingのTimer登録と解除だけをEffectで扱い、Request関数をEffect本体へ直接記述しない
- **必須:** Pollingを停止する条件、間隔、Error時の扱いを明示する
- **推奨:** Client再取得の仕組みをFeature間で安易に共通化しない

## 12. useEffect規約

`useEffect`はReact外部の仕組みと同期する場合だけ使用する。

許可する用途:

- Web Animation APIなどのアニメーション制御
- DOM APIとの同期
- `window`、`document`、`localStorage`などのbrowser API
- browser Eventの購読と解除
- PollingなどのTimer登録と解除
- 外部UIライブラリとの同期

禁止する用途:

- API Request
- Server PropsのStateへの同期
- PropsからStateへの同期
- 派生状態の計算
- ユーザー操作後の業務処理
- API更新の成功または失敗の監視
- `dispatch`による通常の状態遷移

- **必須:** 購読、Timer、Observer、Animationを作成したEffectはcleanupする
- **必須:** Effectが必要な理由を「外部との同期」として説明できるようにする
- **推奨:** Event Handler、Reducer、Selector、API callbackで表現できる処理はEffectへ記述しない

## 13. Design workflowとデザイントークン

### 13.1 Design workflow

新しい画面または既存画面の大幅な再設計は、実装前に短いDesign planを作成する。

1. Subject、Audience、Primary jobを定義する
2. 実データに近いContentと主要な画面状態を用意する
3. 4〜6色のPalette、Typography、Layout、Motionの方針を定める
4. DesktopとMobileの簡潔なWireframeを比較する
5. プロダクト固有の選択か、他の画面にも流用できるGenericな選択かを自己Reviewする
6. Genericな選択を修正してから実装を始める

- **必須:** Palette、Typography、Layoutは対象業務と利用者に基づいて選択する
- **必須:** 実装前に主要情報の優先順位とAlignmentを決める
- **必須:** 実装後にDesktopとMobileのScreenshotで確認する
- **必須:** Keyboard操作、長文、Empty、Error、Reduced Motionを確認する
- **推奨:** 視覚的な大胆さは1箇所へ集中させ、意味のない装飾を削除する
- **推奨:** 本文の1行は原則80文字未満に収める
- **推奨:** 見出しの単語だけを別色、斜体、太字にする定型的な強調を避ける
- **推奨:** 同じ角丸、影、構造を繰り返すだけの汎用Card layoutを避ける

UI Copyは利用者の言葉、能動態、具体的な操作名を使用する。同じ操作はButton、進行表示、完了通知で同じ語彙を使用する。ErrorとEmpty stateでは、状況だけでなく次に取れる操作を示す。

### 13.2 基本方針

色、文字、余白などのDesign decisionは、`shared/styles`のDesign tokenを正本とする。

Design tokenで管理する値:

- 色
- font-family
- font-size
- font-weight
- line-height
- letter-spacing
- spacing
- border width
- border radius
- shadow
- z-index
- breakpoint
- animation duration
- easing
- motion distance

- **必須:** Componentから対象値を直接指定せず、Design tokenを参照する
- **必須:** 新しい値を追加する前に既存Tokenで表現できないことを確認する
- **必須:** 同じ意味を持つTokenを重複して定義しない
- **推奨:** Token名は見た目ではなく用途を表す

### 13.3 Primitive tokenとSemantic token

色はPrimitive tokenとSemantic tokenの2階層で定義する。

```scss
:root {
  // Primitive tokens
  --palette-neutral-0: #ffffff;
  --palette-neutral-900: #17201c;
  --palette-brand-600: #166a4b;

  // Semantic tokens
  --color-text-primary: var(--palette-neutral-900);
  --color-background-primary: var(--palette-neutral-0);
  --color-action-primary: var(--palette-brand-600);
}
```

- **必須:** Primitive tokenはpaletteの定義に限定する
- **必須:** ComponentはSemantic tokenだけを参照する
- **必須:** Componentから`--palette-*`を直接参照しない
- **必須:** ComponentへHEX、RGB、HSLなどのColor literalを記述しない
- **推奨:** Theme切り替えはSemantic tokenの再定義で対応する

### 13.4 Tokenの命名

```text
--palette-{color}-{scale}
--color-{role}-{variant}
--font-family-{role}
--font-size-{role-or-scale}
--font-weight-{scale}
--line-height-{role-or-scale}
--letter-spacing-{role-or-scale}
--space-{scale}
--border-width-{role-or-scale}
--radius-{scale}
--shadow-{role-or-scale}
--z-index-{role}
--duration-{scale}
--easing-{role}
--motion-distance-{scale}
```

使用例:

```scss
.title {
  color: var(--color-text-primary);
  font-size: var(--font-size-heading-md);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  margin-block-end: var(--space-4);
}
```

### 13.5 Motion token

Animationの時間、easing、移動距離はTokenとして定義する。

```scss
:root {
  --duration-instant: 80ms;
  --duration-fast: 120ms;
  --duration-normal: 200ms;
  --duration-slow: 300ms;

  --easing-standard: cubic-bezier(0.2, 0, 0, 1);
  --easing-emphasized: cubic-bezier(0.2, 0, 0, 1.2);

  --motion-distance-sm: 0.25rem;
  --motion-distance-md: 0.5rem;
}
```

- **必須:** Componentへduration、easing、motion distanceのliteralを直接記述しない
- **必須:** Motionを採用する場合、操作を補助するAnimationは原則として300ms以内に完了させる
- **必須:** 無限に繰り返すAnimationはLoadingなど継続状態の表現に限定する
- **推奨:** 通常の操作Feedbackには`--duration-fast`または`--duration-normal`を使用する

### 13.6 Breakpoint

CSS Custom PropertyはMedia Queryの条件に使用できないため、Breakpointは`_breakpoints.scss`のSCSS変数として定義する。

```scss
$breakpoint-mobile: 40rem;
$breakpoint-tablet: 64rem;
$breakpoint-desktop: 80rem;
```

- **必須:** Media QueryへBreakpointのliteralを直接記述しない
- **推奨:** Mobile firstでStyleを定義する

### 13.7 Literalを許可する値

次のようなDesign decisionではない構造値は直接指定できる。

- `0`
- `100%`
- `auto`
- `1fr`
- `inherit`
- `currentColor`
- Gridの列数など、Component構造だけに依存する値

同じ値が複数箇所に現れる、またはデザイン上の意味を持つ場合はToken化を検討する。

## 14. SCSS規約

- **必須:** Component StyleにはSCSS Modulesを使用する
- **必須:** Global Styleは`shared/styles/globals.scss`だけに記述する
- **必須:** `globals.scss`をRoot Layoutから一度だけ読み込む
- **必須:** ID SelectorをStyle目的で使用しない
- **必須:** `!important`を原則使用しない
- **必須:** 他Componentの内部Classを上書きしない
- **推奨:** Selectorのnestは3階層以内にする
- **推奨:** CSS ModulesではBEMを使用せず、責務が分かるcamelCaseを使用する
- **推奨:** Logical Propertiesを使用し、方向依存を減らす
- **推奨:** MobileとDesktopの双方で表示を確認する

```tsx
import styles from "./CampaignView.module.scss";

export function CampaignView() {
  return <section className={styles.root}>...</section>;
}
```

## 15. Motionと操作導線

### 15.1 基本方針

操作可能なComponentには、Hover、Focus、Active、Disabled、Loading、Errorなどの視覚的なFeedbackを設ける。FeedbackにAnimationを使用することは必須ではない。

- **必須:** Button、Link、入力、選択肢、Accordion、Dialog、操作可能なCardなどに操作Feedbackを設ける
- **必須:** Hoverだけに依存せず、Keyboard向けのFocusと押下時のActive状態を設ける
- **必須:** Animationだけで操作可能性や状態を伝えない
- **必須:** Disabled状態では操作可能に見えるAnimationを無効化する
- **推奨:** Motionは状態変化、空間関係、操作結果の理解を助ける場合だけ使用する
- **推奨:** ユーザー操作によらないMotionは1つの意図的な演出へ絞り、各SectionへのFadeとSlideの反復を避ける

装飾だけを目的とした連続Animation、すべてのCardへのHover Motion、操作よりも目立つ大きな移動は使用しない。

### 15.2 Animationの用途

| Feedback       | 用途                                         |
| -------------- | -------------------------------------------- |
| Hover          | Pointerで操作できることを示す                |
| Focus          | Keyboard操作の対象を示す                     |
| Active         | 操作を受け付けたことを示す                   |
| Fade           | 表示、非表示、状態の切り替えを示す           |
| Slide          | Panel、Dialog、Accordionなどの移動関係を示す |
| Progress       | 読取、更新、送信処理中であることを示す       |
| Error feedback | 入力Errorや操作失敗へ注意を向ける            |

### 15.3 実装規約

CSS TransitionとCSS Animationを第一選択とする。

```scss
.root {
  transform-origin: center;
  transition: transform var(--duration-fast) var(--easing-standard);

  &:hover {
    transform: translateY(calc(var(--motion-distance-sm) * -1));
  }

  &:active {
    transform: translateY(0);
  }

  &:focus-visible {
    outline: var(--focus-ring-width) solid var(--color-focus-ring);
    outline-offset: var(--focus-ring-offset);
  }

  &:disabled {
    transform: none;
  }
}
```

- **必須:** AnimationのStyleを対象ComponentのSCSS Moduleへ記述する
- **必須:** Animation対象は`transform`と`opacity`に限定する
- **必須:** `transition: all`を使用せず、対象Propertyを列挙する
- **必須:** Motionの支点に合う`transform-origin`を指定する
- **必須:** Animationをユーザー操作で中断できるようにする
- **必須:** SVGは必要に応じてwrapperまたは`<g>`をAnimation対象にし、`transform-box`と`transform-origin`を指定する
- **必須:** Animation完了をAPI Requestや業務処理の開始条件にしない
- **必須:** API Requestは操作直後に開始し、Animation終了を待たない
- **必須:** Animation状態をDomain stateまたはReducerへ保存しない
- **必須:** `animationend`を業務Eventとして扱わない
- **必須:** 5秒を超える自動Motionには停止、非表示、一時停止の操作を提供する
- **推奨:** 複雑な時系列制御が必要な場合だけWeb Animations APIを使用する

Web Animations APIを`useEffect`で利用する場合は、Animationをcleanupする。表示状態はViewModelから受け取り、Animationを理由にReducer Eventを発行しない。

### 15.4 Reduced Motion

`prefers-reduced-motion`へ対応し、利用者が動きを減らせるようにする。

```scss
@media (prefers-reduced-motion: reduce) {
  .root {
    animation: none;
    transition: none;
    transform: none;
  }
}
```

- **必須:** Motionを持つComponentにReduced Motion時のStyleを定義する
- **必須:** Motionを無効化しても要素を表示、理解、操作できるようにする
- **必須:** Motionが伝えていた状態をText、Icon、形状など、Motion以外の表現でも確認できるようにする
- **必須:** Reduced Motion時もFocus、Active、Loading、Errorを識別できるようにする

## 16. API通信

- **必須:** Browserからは同一Originの`/api/*`を呼び出す
- **必須:** `fetch`をUI Componentから直接呼び出さない
- **必須:** Browser向け共通Request処理を`shared/api/browserApiClient.ts`へ集約する
- **必須:** Server向け共通Request処理を`shared/api/serverApiClient.ts`へ集約し、`server-only`を指定する
- **必須:** Feature固有の更新処理を`features/<feature>/api`へ配置する
- **必須:** Feature固有の読取処理を`features/<feature>/server`へ配置する
- **必須:** 非2xx、Network Error、Timeout、Response parse failureを区別する
- **必須:** APIのError codeを処理分岐に使用し、Message文字列で分岐しない
- **必須:** RequestとResponseへ型を定義する
- **必須:** Secretを`NEXT_PUBLIC_*`環境変数へ設定しない
- **推奨:** `AbortSignal`でRequestのTimeoutまたは中断を扱う

## 17. フォームと最終承認

施策案と投稿案のフォームでは「手書き修正」「Agentと再相談」「最終承認」を明確に分離する。

### 17.1 手書き修正

- **必須:** 中間編集をReducerのローカルStateだけに保持する
- **必須:** 入力変更ごとにAgent履歴または業務DBへ保存しない
- **必須:** 入力変更にLLMを使用しない

### 17.2 Agentと再相談

- **必須:** 現在のフォーム値とユーザーの修正指示を送信する
- **必須:** 新しい提案結果でフォームを置き換える処理をEventとして表現する
- **必須:** 再相談を最終承認として扱わない

### 17.3 最終承認

- **必須:** 承認時点のフォーム値をRequest Bodyの正本とする
- **必須:** 現在利用中の親Session IDをAPI Pathへ設定する
- **必須:** 承認操作ごとにUUID形式の`Idempotency-Key`を生成する
- **必須:** Headerの`Idempotency-Key`と監査内容のAction IDへ同じ値を設定する
- **必須:** 二重Click、通信切断後の再送、内部再試行では同じKeyを再利用する
- **必須:** ユーザーが明示的に新しい承認操作を行った場合だけ新しいKeyを生成する
- **必須:** 承認処理中は同じ操作の重複実行を防ぐ
- **必須:** Agentの自由文応答を施策保存またはX投稿の最終承認として扱わない

Idempotency-Keyの生成、保持、再利用、破棄はcontrollerとReducer Eventで明示的に管理する。

## 18. Errorと画面状態

すべてのServer data表示は次の状態を考慮する。

- Initial loading
- Refreshing
- Empty
- Success
- Recoverable error
- Non-recoverable error

- **必須:** Error時に利用者が取れる次の操作を表示する
- **必須:** Backendの内部情報、Stack trace、Secretを表示しない
- **必須:** `AGENT_SESSION_NOT_FOUND`では有効な親Sessionの選択または作成へ誘導する
- **必須:** `IDEMPOTENCY_REQUEST_IN_PROGRESS`では同じKeyを使用して結果を再取得する
- **必須:** `outcome_unknown`のX投稿を自動再実行しない
- **推奨:** Error codeから表示内容へ変換する処理をcontrollerまたは専用Mapperへ置く

## 19. Accessibility

- **必須:** 操作には適切な`button`、`a`、`input`などのSemantic HTMLを使用する
- **必須:** Actionには`button`、Navigationには`a`または`Link`を使用する
- **必須:** 入力項目へVisibleな`label`または同等のAccessible Nameを設定する
- **必須:** IconだけのButtonへ具体的な`aria-label`を設定する
- **必須:** 装飾Iconへ`aria-hidden="true"`を設定する
- **必須:** Imageへ用途に合う`alt`を設定し、装飾Imageは`alt=""`とする
- **必須:** Headingを`h1`から階層順に使用し、Main contentへのSkip linkを用意する
- **必須:** Keyboardだけで主要操作を完了できるようにする
- **必須:** Focus indicatorを削除しない
- **必須:** `:focus-visible`を使用し、Sticky要素やOverlayでFocus対象を隠さない
- **必須:** Hoverで示す操作Feedbackを`focus-visible`でも提供する
- **必須:** 色だけで状態を伝えない
- **必須:** Animationだけで状態や操作可能性を伝えない
- **必須:** Form controlへ意味のある`name`、`autocomplete`、`type`、`inputmode`を設定する
- **必須:** `onPaste`で貼り付けを禁止しない
- **必須:** Form Errorを入力の近くへ表示し、`aria-describedby`で関連付ける
- **必須:** Submit失敗時は最初のError項目へFocusを移動する
- **必須:** Loading、Validation、Toastなどの非同期更新を`aria-live="polite"`などで通知する
- **必須:** 未保存の編集内容がある状態での離脱前に警告する
- **必須:** 破壊的操作には確認手段またはUndo期間を設ける
- **必須:** Drag、Swipe、PinchなどのGesture操作へClickとKeyboardの代替を用意する
- **必須:** Dialog、Drawer、Sheetへ`overscroll-behavior: contain`を指定する
- **必須:** `prefers-reduced-motion`へ対応する
- **推奨:** Dialog表示後と終了後のFocusを管理し、`autoFocus`はDesktopの明確な主入力だけに限定する
- **推奨:** 長文、空文字、非常に長いユーザー入力でもLayoutが壊れないようにする
- **推奨:** 日時と数値の表示には`Intl.DateTimeFormat`と`Intl.NumberFormat`を使用する

## 20. Security

- **必須:** `dangerouslySetInnerHTML`を原則使用しない
- **必須:** 外部Contentを安全なHTMLとして信用しない
- **必須:** 認証・認可をFrontendだけで保証しない
- **必須:** Cookie認証を使用するPOST・PUT・PATCH・DELETEではBackendのCSRF方式に従う
- **必須:** Token、Secret、個人情報をConsoleへ出力しない
- **必須:** URL、localStorage、API Responseを信頼済み入力として扱わない

## 21. Performance

- **必須:** 根拠のない`useMemo`と`useCallback`を追加しない
- **必須:** EffectでRender回数を調整しない
- **必須:** Animationによる意図しないLayout shiftを発生させない
- **必須:** 独立した非同期処理を直列に待たず、並列に開始する
- **必須:** Barrel file経由の広いimportを避け、対象moduleから直接importする
- **必須:** Server ComponentからClient Componentへ渡す値を最小化する
- **必須:** Imageの`width`と`height`を指定し、表示位置に応じてLazy loadまたはPriorityを設定する
- **必須:** Render中に`getBoundingClientRect`、`offsetHeight`などのLayout readを行わない
- **必須:** DOM readとDOM writeを交互に実行せず、処理をまとめる
- **必須:** ScrollとTouchのListenerは動作を妨げない場合にpassiveとする
- **推奨:** 重量Componentは`next/dynamic`で遅延読込する
- **推奨:** AnalyticsなどのThird-party ScriptはHydration後へ遅延する
- **推奨:** 50件を超えるListはVirtualizationまたは`content-visibility: auto`を検討する
- **推奨:** Critical fontはpreloadし、`font-display: swap`を設定する
- **推奨:** 頻繁なGlobal Event Listenerは重複登録しない
- **推奨:** 重い更新には`startTransition`を検討する
- **推奨:** 入力中も古い結果を表示できる検索には`useDeferredValue`を検討する
- **推奨:** Effect内で最新の値を参照する必要がある場合は`useEffectEvent`を検討する
- **推奨:** 最適化は計測結果をもとに行う

## 22. Test規約

v0.1では実装時間を優先し、画面上の各ユーザー操作について、正常に完了する経路を1件通すE2E Testだけを必須とする。

### 22.1 必須範囲

- **必須:** `SCREEN_DESIGN.md`で定義した各ユーザー操作が、少なくとも1つの正常系E2E Testに含まれること
- **必須:** Browserから操作し、画面遷移、表示結果、対象APIとの接続を確認すること
- **必須:** 1つのE2E Scenarioで複数のユーザー操作を続けて確認してよい
- **必須:** 各ユーザー操作と、それを確認するE2E Scenarioの対応を追跡できること
- **必須:** Test間でFixture、Mock、Browser stateを共有せず、実行順に依存しないこと
- **必須:** X、GA4、LLM、Embeddingなどの外部Serviceを実際に呼ばず、固定Fakeを使用すること
- **必須:** 時刻、乱数、IDおよび外部応答を固定し、同じ結果を再現できること
- **必須:** 実装詳細ではなく、ユーザー操作と画面上の観測可能な結果を検証すること

「各ユーザー操作」は、Button Clickのような個々のDOM Eventではなく、ログイン、会話開始、メッセージ送信、施策承認、X投稿公開、検索、編集、削除、ログアウトなど、利用者が目的を持って行う操作を指す。

### 22.2 必須としないTest

次のTestはv0.1では必須としない。必要性が生じた場合に追加してよいが、網羅を求めない。

- Component、Controller、Reducer、Selector、純粋関数のUnit Test
- 異常系、境界値、入力不正、通信失敗のTest
- Loading、Empty、Errorなど画面状態ごとのTest
- Keyboard、Focus、Accessible Name、Reduced Motionなどの自動Test
- Browser、Viewport、OSの組み合わせを網羅するTest
- Code Coverageの目標設定

E2E TestのRunner、配置、File命名、実行Commandは、E2E環境の導入時に決定する。Component test libraryはv0.1では導入対象としない。

## 23. 禁止事項

- UI Componentへのドメインロジック記述
- UI ComponentからのAPI直接呼び出し
- Feature状態の`useState`による分散管理
- `useEffect`による状態管理
- 読取専用Server PropsのReducerへのコピー
- PropsとStateのEffectによる同期
- Eventを経由しないReducer Stateの変更
- Component内でのDesign valueの直接指定
- Animation duration、easing、motion distanceの直接指定
- Animation完了を条件とするAPI Requestまたは業務処理
- 装飾だけを目的とする連続Animation
- `transition: all`
- Feature間の無秩序な直接参照
- 型検証を回避する`any`または安易な型アサーション
- Secretを含む`NEXT_PUBLIC_*`環境変数

## 24. 品質確認

Pull Requestを作成する前に次を実行する。

```bash
npm run lint
npm run build
```

E2E環境導入後は、22章で定める正常系E2E Testを必須確認へ追加する。

Reviewでは最低限、次を確認する。

- 依存方向が守られている
- UIが純粋に保たれている
- Feature状態がReducerとEventで管理されている
- 通常の読取がServer Componentと型付けされたServer関数で実装されている
- Client更新が責務別controllerと型付けされたAPI clientで実装されている
- `useEffect`が外部同期以外に使われていない
- Design tokenが使用されている
- ComponentとSCSS Moduleが1対1になっている
- 操作可能なComponentにHover、Focus、ActiveなどのFeedbackがある
- Animationが必要な箇所だけへ意図的に使用されている
- Reduced Motionでも表示と操作が成立する
- Animationが操作を遅延させず、Layout shiftを発生させない
- Loading、Empty、Error、Successが考慮されている
- AccessibilityとSecurityの要件を満たしている
- 最終承認とIdempotency-Keyの規約を満たしている

## 25. 現行実装からの移行

本書作成時点では、Frontendは最小の疎通確認画面であり、次の項目は未導入である。

- `features/`と`shared/`のディレクトリ構成
- SCSSとSCSS Modules
- Design token
- Reducerとcontrollerによる状態管理
- Frontend E2E環境

今後のFeature実装開始時に次を実施する。

1. `sass`を追加する
2. `app/globals.css`を`shared/styles/globals.scss`へ移行する
3. Design tokenを`shared/styles/_tokens.scss`へ定義する
4. 現行画面をServer Component、責務別controller、純粋UIへ分割する
5. Server用とBrowser用の型付けされたAPI clientを定義する
6. E2E Test runner、配置、File命名、実行Commandを決定する

移行が完了するまでは既存コードとの差分を認識し、新規Featureを旧構成へ追加しない。
