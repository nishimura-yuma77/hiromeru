"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/shared/api/ApiError";

import { approveCampaign, approveXPost } from "../api";
import { useChatController } from "../controller";
import type { AgentTurn, ApprovalAction, ApprovalState, CampaignProposal, SecurityNotice, SessionHistory, TurnItem, XPostProposal } from "../types";
import styles from "../styles/Chat.module.scss";

const dateFormatter = new Intl.DateTimeFormat("ja-JP", { hour: "2-digit", minute: "2-digit" });
const examples = [
  "新しい採用施策を考える",
  "既存の施策から投稿案を作る",
  "公開済み投稿の結果を振り返る",
];

const activityLabels: Record<string, string> = {
  get_session_items: "会話履歴を確認中",
  search_long_term_memory: "記憶を検索中",
  save_long_term_memory: "記憶を保存中",
  delete_long_term_memory: "記憶を削除中",
  web_search: "Webを検索中",
  web_fetch: "Web情報を確認中",
  get_campaign: "施策を確認中",
  search_campaigns: "施策を確認中",
  get_post: "投稿を確認中",
  search_posts: "投稿を確認中",
  get_marketing_metrics: "計測結果を確認中",
  run_campaign_planner: "施策を立案中",
  run_content_creator: "投稿案を作成中",
  propose_campaign: "施策案を整理中",
  propose_x_post: "投稿案を整理中",
};

const noticeLabels: Record<string, string> = {
  prompt_injection: "外部の情報に、AIへの不正な指示が含まれている可能性を検出しました",
  sensitive_data: "機密情報が含まれている可能性を検出しました",
  unauthorized_tool_call: "許可されていない操作を検出しました",
  unsafe_external_action: "外部への安全でない操作を検出しました",
};

type ApprovalAudit = { action: ApprovalAction; state: ApprovalState; success: boolean | null };

function requestSignature(value: Record<string, unknown>) {
  return JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))));
}

function campaignRequest(value: CampaignProposal): Record<string, unknown> {
  const request: Record<string, unknown> = {
    title: value.title,
    target_profile: value.target_profile,
    background: value.background,
    objective: value.objective,
    plan: value.plan,
  };
  if (value.id !== null) {
    request.id = value.id;
    request.expected_updated_at = value.expected_updated_at;
  }
  return request;
}

function activityResult(status: ActivityStatus) {
  if (status === "succeeded") return "完了";
  if (status === "failed") return "失敗";
  return "安全のため停止";
}

type ActivityStatus = "succeeded" | "failed" | "blocked";

function ProposalForm({ item, sessionId, audits, refreshHistory }: {
  item: Extract<TurnItem, { type: "campaign_proposal" | "x_post_proposal" }>;
  sessionId: number;
  audits: ApprovalAudit[];
  refreshHistory: () => Promise<void>;
}) {
  const campaign = item.type === "campaign_proposal";
  const [values, setValues] = useState<CampaignProposal | XPostProposal>(item.content);
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [success, setSuccess] = useState<string | null>(null);
  const keyRef = useRef<{ signature: string; key: string } | null>(null);
  const request = campaign ? campaignRequest(values as CampaignProposal) : values as XPostProposal;
  const signature = requestSignature(request as Record<string, unknown>);
  const operation = campaign ? "upsert_campaign" : "publish_x_post";
  const audit = audits.findLast((entry) => entry.state.operation === operation && requestSignature(entry.action.request) === signature);
  const unresolved = audit?.state.status === "outcome_unknown" || audit?.state.recovery === "manual_reconciliation";
  const externalSucceeded = audit?.state.external_succeeded === true;
  const completed = audit?.state.status === "succeeded";
  const locked = completed || unresolved;

  function update(field: string, value: string) {
    setValues((current) => ({
      ...current,
      [field]: field === "campaign_id" ? Number(value) : value,
    }));
    setConfirming(false);
    setGeneralError(null);
    setSuccess(null);
    setFieldErrors((current) => {
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  async function submit() {
    if (submitting || locked) return;
    setSubmitting(true);
    setGeneralError(null);
    setFieldErrors({});
    let key = audit?.action.id;
    if (!key) {
      if (keyRef.current?.signature !== signature) keyRef.current = { signature, key: crypto.randomUUID() };
      key = keyRef.current.key;
    }
    try {
      if (campaign) {
        await approveCampaign(sessionId, values as CampaignProposal, key);
        setSuccess("施策を承認して保存しました。");
      } else {
        await approveXPost(sessionId, values as XPostProposal, key);
        setSuccess(externalSucceeded ? "公開済み投稿の保存を完了しました。" : "Xへの投稿を公開しました。");
      }
      setConfirming(false);
    } catch (error) {
      if (error instanceof ApiError) {
        setGeneralError(error.code === "X_POST_OUTCOME_UNKNOWN"
          ? "Xへの公開結果を確認できません。再投稿せず、運用担当による照合をお待ちください。"
          : error.code === "X_POST_SAVE_FAILED"
            ? "Xへの公開は完了しています。再試行すると、同じ処理キーで保存だけを完了します。"
            : error.message);
        setFieldErrors(Object.fromEntries(error.fieldErrors.filter((entry) => entry.field).map((entry) => [entry.field as string, entry.message])));
        const summary = error.fieldErrors.find((entry) => entry.field === null);
        if (summary) setGeneralError(summary.message);
      } else {
        setGeneralError("処理結果を確認できませんでした。同じ内容で再試行できます。");
      }
    } finally {
      try { await refreshHistory(); } catch { /* Keep the actionable result visible if history refresh fails. */ }
      setSubmitting(false);
    }
  }

  const statusMessage = unresolved
    ? "公開結果を確認中です。二重投稿を防ぐため、この内容は再送できません。"
    : completed
      ? campaign ? "この施策は承認済みです。" : "この投稿は公開済みです。"
      : externalSucceeded
        ? "Xへの公開は完了しています。新しく投稿せず、保存処理だけを再試行できます。"
        : null;

  return (
    <article className={styles.proposalCard}>
      <header><span className={styles.proposalEyebrow}>{campaign ? "CAMPAIGN PROPOSAL" : "X POST PROPOSAL"}</span><h3>{campaign ? "施策案" : "X投稿案"}</h3><p>内容を確認し、必要な箇所を直接編集できます。</p></header>
      <div className={styles.proposalFields}>
        {campaign ? <>
          <ProposalField disabled={locked || submitting} error={fieldErrors.title} idPrefix={item.item_id} label="施策タイトル" name="title" onChange={update} value={(values as CampaignProposal).title} />
          <ProposalField disabled={locked || submitting} error={fieldErrors.target_profile} idPrefix={item.item_id} label="ターゲット像" multiline name="target_profile" onChange={update} value={(values as CampaignProposal).target_profile} />
          <ProposalField disabled={locked || submitting} error={fieldErrors.background} idPrefix={item.item_id} label="実施背景" multiline name="background" onChange={update} value={(values as CampaignProposal).background} />
          <ProposalField disabled={locked || submitting} error={fieldErrors.objective} idPrefix={item.item_id} label="施策目的" multiline name="objective" onChange={update} value={(values as CampaignProposal).objective} />
          <ProposalField disabled={locked || submitting} error={fieldErrors.plan} idPrefix={item.item_id} label="施策内容" multiline name="plan" onChange={update} value={(values as CampaignProposal).plan} />
        </> : <>
          <ProposalField disabled={locked || submitting} error={fieldErrors.campaign_id} idPrefix={item.item_id} label="施策ID" name="campaign_id" onChange={update} type="number" value={String((values as XPostProposal).campaign_id)} />
          <ProposalField disabled={locked || submitting} error={fieldErrors.body} idPrefix={item.item_id} label="投稿本文" multiline name="body" onChange={update} value={(values as XPostProposal).body} />
          <ProposalField disabled={locked || submitting} error={fieldErrors.landing_url} idPrefix={item.item_id} label="遷移先URL" name="landing_url" onChange={update} type="url" value={(values as XPostProposal).landing_url} />
          <span className={styles.characterCount}>{(values as XPostProposal).body.length.toLocaleString("ja-JP")}文字（URLを除く）</span>
        </>}
      </div>
      {statusMessage ? <p className={`${styles.approvalNotice} ${unresolved ? styles.approvalWarning : ""}`} role="status">{statusMessage}</p> : null}
      {generalError ? <p className={styles.proposalError} role="alert">{generalError}</p> : null}
      {success ? <p className={styles.proposalSuccess} role="status">{success}</p> : null}
      {!locked ? confirming ? (
        <div className={styles.confirmApproval}>
          <p>{campaign ? "この内容を最終承認して保存しますか？" : externalSucceeded ? "Xへ再投稿せず、保存処理だけを再試行しますか？" : "この内容を最終承認してXへ公開しますか？"}</p>
          <div><button className={styles.secondaryButton} disabled={submitting} onClick={() => setConfirming(false)} type="button">戻る</button><button disabled={submitting} onClick={() => void submit()} type="button">{submitting ? "処理中…" : campaign ? "承認を確定" : externalSucceeded ? "保存を再試行" : "公開を確定"}</button></div>
        </div>
      ) : <button className={styles.approveButton} disabled={submitting} onClick={() => setConfirming(true)} type="button">{campaign ? "承認して保存" : externalSucceeded ? "保存処理を再試行" : "承認して公開"}</button> : null}
    </article>
  );
}

function ProposalField({ disabled, error, idPrefix, label, multiline = false, name, onChange, type = "text", value }: {
  disabled: boolean; error?: string; idPrefix: number; label: string; multiline?: boolean; name: string;
  onChange: (name: string, value: string) => void; type?: string; value: string;
}) {
  const id = `proposal-${idPrefix}-${name}`;
  return <label className={styles.proposalField} htmlFor={id}><span>{label}</span>{multiline
    ? <textarea aria-describedby={error ? `${id}-error` : undefined} aria-invalid={Boolean(error)} disabled={disabled} id={id} onChange={(event) => onChange(name, event.target.value)} rows={3} value={value} />
    : <input aria-describedby={error ? `${id}-error` : undefined} aria-invalid={Boolean(error)} disabled={disabled} id={id} min={type === "number" ? 1 : undefined} onChange={(event) => onChange(name, event.target.value)} type={type} value={value} />}{error ? <small id={`${id}-error`}>{error}</small> : null}</label>;
}

function Item({ item, sessionId, audits, refreshHistory }: { item: TurnItem; sessionId: number; audits: ApprovalAudit[]; refreshHistory: () => Promise<void> }) {
  if (item.type === "user_message" || item.type === "assistant_message") {
    const user = item.type === "user_message";
    return (
      <article className={`${styles.message} ${user ? styles.userMessage : styles.assistantMessage}`}>
        <span className={styles.speaker}>{user ? "あなた" : "Hiromeru AI"}</span>
        <p>{item.content.text}</p>
        <time dateTime={item.created_at}>{dateFormatter.format(new Date(item.created_at))}</time>
      </article>
    );
  }

  if (item.type === "campaign_proposal" || item.type === "x_post_proposal") {
    return <ProposalForm audits={audits} item={item} refreshHistory={refreshHistory} sessionId={sessionId} />;
  }

  if (item.type === "approval_action") {
    const type = item.content.type;
    const label = type === "publish_x_post" ? "X投稿を承認して公開しました" : "施策を最終承認しました";
    return (
      <article className={`${styles.message} ${styles.userMessage}`}>
        <span className={styles.speaker}>あなた</span>
        <p>{label}</p>
        <details><summary>承認内容を見る</summary><pre>{JSON.stringify(item.content.request, null, 2)}</pre></details>
        <time dateTime={item.created_at}>{dateFormatter.format(new Date(item.created_at))}</time>
      </article>
    );
  }

  if (item.type === "api_result") {
    const success = item.content.success === true;
    return (
      <article className={`${styles.message} ${styles.systemMessage}`}>
        <span className={styles.speaker}>システム</span>
        <p>{success ? "処理が完了しました。" : "処理を完了できませんでした。"}</p>
        {!success && item.content.error ? <p>{item.content.error.message}</p> : null}
        <time dateTime={item.created_at}>{dateFormatter.format(new Date(item.created_at))}</time>
      </article>
    );
  }

  return (
    <article className={`${styles.message} ${styles.unknownMessage}`}>
      <span className={styles.speaker}>システム</span>
      <p>この種類の項目はまだ表示に対応していません。</p>
      <code>{item.original_type}</code>
      <time dateTime={item.created_at}>{dateFormatter.format(new Date(item.created_at))}</time>
    </article>
  );
}

function Notices({ notices }: { notices: SecurityNotice[] }) {
  if (notices.length === 0) return null;
  const grouped = new Map<string, { notice: SecurityNotice; count: number }>();
  for (const notice of notices) {
    const key = `${notice.event_type}:${notice.enforcement}`;
    const found = grouped.get(key);
    grouped.set(key, { notice, count: (found?.count ?? 0) + 1 });
  }
  return (
    <div className={styles.notices} role="status">
      {[...grouped.values()].map(({ notice, count }) => (
        <p key={`${notice.event_type}:${notice.enforcement}`}>
          {noticeLabels[notice.event_type] ?? "安全性に関する通知があります"}{count > 1 ? `（${count}件）` : ""}
        </p>
      ))}
    </div>
  );
}

function ApprovalStatus({ state }: { state: ApprovalState }) {
  const label = state.operation === "publish_x_post" ? "X投稿" : "施策";
  let message = `${label}の承認処理中です。`;
  if (state.status === "succeeded") message = `${label}の承認が完了しました。`;
  if (state.status === "failed") message = `${label}の承認を完了できませんでした。`;
  if (state.status === "outcome_unknown") message = "Xへの公開結果を確認中です。再投稿せず、運用担当による照合をお待ちください。";
  if (state.external_succeeded && state.status === "processing") message = "Xへの公開は完了しています。投稿データの保存完了を待っています。";
  return <div className={`${styles.approvalState} ${state.status === "failed" || state.status === "outcome_unknown" ? styles.approvalWarning : ""}`} role="status"><strong>{message}</strong>{state.recovery === "retry_same_key" ? <span>同じ処理キーで保存のみ再試行できます。</span> : null}</div>;
}

function Turn({ turn, restore, sessionId, audits, refreshHistory }: { turn: AgentTurn; restore: (message: string) => void; sessionId: number; audits: ApprovalAudit[]; refreshHistory: () => Promise<void> }) {
  const userText = turn.items.find((item) => item.type === "user_message");
  return (
    <li className={styles.turn}>
      {[...turn.items].sort((a, b) => a.item_number - b.item_number).map((item) => <Item audits={audits} item={item} key={item.item_id} refreshHistory={refreshHistory} sessionId={sessionId} />)}
      {turn.approval_state ? <ApprovalStatus state={turn.approval_state} /> : null}
      <Notices notices={turn.security_notices} />
      {turn.error ? (
        <div className={styles.turnError} role="alert">
          <p>{turn.error.message}</p>
          {userText?.type === "user_message" ? <button onClick={() => restore(userText.content.text)} type="button">同じ内容を入力欄へ戻す</button> : null}
        </div>
      ) : null}
    </li>
  );
}

export function Conversation({ initialHistory, initialDraft = "" }: { initialHistory: SessionHistory | null; initialDraft?: string }) {
  const { state, dispatch, send, loadEarlier, refreshHistory, maxLength } = useChatController(initialHistory);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (initialDraft) dispatch({ type: "draft", value: initialDraft });
    textareaRef.current?.focus();
  }, [dispatch, initialDraft]);

  useEffect(() => {
    const element = messagesRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [state.turns.length, state.pendingMessage]);

  function restore(message: string) {
    dispatch({ type: "draft", value: message });
    textareaRef.current?.focus();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.nativeEvent.isComposing || event.key !== "Enter" || (!event.ctrlKey && !event.metaKey)) return;
    event.preventDefault();
    void send();
  }

  const title = state.session?.title ?? (state.session ? "無題の会話" : "新しい会話");
  const invalid = !state.draft.trim() || state.draft.length > maxLength;
  const audits = state.turns.flatMap((turn): ApprovalAudit[] => {
    if (!turn.approval_state) return [];
    const action = turn.items.find((item): item is Extract<TurnItem, { type: "approval_action" }> => item.type === "approval_action");
    if (!action) return [];
    const result = turn.items.find((item): item is Extract<TurnItem, { type: "api_result" }> => item.type === "api_result");
    return [{ action: action.content, state: turn.approval_state, success: result?.content.success ?? null }];
  });

  return (
    <div className={styles.conversation}>
      <header className={styles.conversationHeader}>
        <Link href="/chat" aria-label="会話一覧へ戻る">← <span>会話一覧へ戻る</span></Link>
        <h2>{title}</h2>
      </header>
      <div className={styles.messages} ref={messagesRef}>
        {!state.session && state.turns.length === 0 && !state.pendingMessage ? (
          <section className={styles.welcome}>
            <p className={styles.eyebrow}>HIROMERU AI</p>
            <h1>何から始めましょうか。</h1>
            <p>採用施策づくりや投稿案、公開後の振り返りについて相談できます。</p>
            <div className={styles.examples}>
              {examples.map((example) => <button key={example} onClick={() => restore(example)} type="button">{example}</button>)}
            </div>
          </section>
        ) : null}
        {state.hasMore ? (
          <button className={styles.earlierButton} disabled={state.loadingHistory || state.sending} onClick={() => void loadEarlier()} type="button">
            {state.loadingHistory ? "以前の会話を読み込み中" : "以前の会話を読み込む"}
          </button>
        ) : null}
        <ol className={styles.turns}>
          {state.turns.map((turn) => <Turn audits={audits} key={turn.agent_turn_id} refreshHistory={refreshHistory} restore={restore} sessionId={state.session?.session_id ?? 0} turn={turn} />)}
        </ol>
        {state.pendingMessage ? (
          <div className={styles.pendingTurn}>
            <article className={`${styles.message} ${styles.userMessage}`}>
              <span className={styles.speaker}>あなた</span><p>{state.pendingMessage}</p>
            </article>
            <div aria-live="polite" className={styles.progress} role="status">
              <span className={styles.speaker}>Hiromeru AI</span>
              <p><span aria-hidden="true" className={styles.spinner} />{state.recovering ? "結果を確認中" : activityLabels[state.activities.findLast((item) => item.status === "running")?.name ?? ""] ?? "考えています"}</p>
              {state.activities.filter((item): item is typeof item & { status: ActivityStatus } => item.status !== "running").slice(-3).map((activity) => <small className={activity.status === "succeeded" ? undefined : styles.activityProblem} key={activity.activity_id}>{activityLabels[activity.name] ?? "処理"} {activityResult(activity.status)}</small>)}
            </div>
          </div>
        ) : null}
        {state.requestError ? <p className={styles.requestError} role="alert">{state.requestError}</p> : null}
      </div>
      <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void send(); }}>
        <label htmlFor="chat-message">メッセージ</label>
        <textarea
          aria-describedby="chat-counter chat-error chat-status"
          id="chat-message"
          onChange={(event) => dispatch({ type: "draft", value: event.target.value })}
          onKeyDown={handleKeyDown}
          placeholder="相談したいことを入力してください"
          ref={textareaRef}
          rows={3}
          value={state.draft}
        />
        <div className={styles.composerFooter}>
          <div>
            <span className={state.draft.length > maxLength ? styles.counterError : ""} id="chat-counter">{state.draft.length.toLocaleString("ja-JP")} / {maxLength.toLocaleString("ja-JP")}</span>
            <span className={styles.validationError} id="chat-error">{state.composerError}</span>
            <span className={styles.srOnly} id="chat-status" aria-live="polite">{state.sending ? "回答が完了すると送信できます" : ""}</span>
          </div>
          <button disabled={invalid || state.sending} type="submit">{state.sending ? "送信中" : "送信"}</button>
        </div>
        <p className={styles.shortcut}>Ctrl / ⌘ + Enter で送信</p>
      </form>
    </div>
  );
}
