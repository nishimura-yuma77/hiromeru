"use client";

import Link from "next/link";
import { useEffect, useEffectEvent, useReducer, useRef, useState } from "react";

import { getCampaign } from "@/features/campaigns/api/getCampaign";
import type { CampaignListItem } from "@/features/campaigns/types/campaign";
import { ApiError } from "@/shared/api/ApiError";

import { approveCampaign, approveXPost, searchActiveCampaigns } from "../api";
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

type ApprovalAudit = { action: ApprovalAction; state: ApprovalState; errorCode: string | null };
type Proposal = CampaignProposal | XPostProposal;
type ProposalSuccess = { message: string; href: string; linkLabel: string };
type ProposalState = {
  values: Proposal;
  confirming: boolean;
  submitting: boolean;
  generalError: string | null;
  fieldErrors: Record<string, string>;
  success: ProposalSuccess | null;
  revising: boolean;
  revision: string;
};
type ProposalAction =
  | { type: "change"; field: string; value: string }
  | { type: "reset"; values: Proposal }
  | { type: "confirm"; value: boolean }
  | { type: "submit_started" }
  | { type: "submit_finished" }
  | { type: "error"; general: string | null; fields?: Record<string, string> }
  | { type: "success"; value: ProposalSuccess }
  | { type: "revision_open"; value: boolean }
  | { type: "revision"; value: string };

const CAMPAIGN_TITLE_MAX = 255;
const CAMPAIGN_TEXT_MAX = 10_000;
const LANDING_URL_MAX = 2048;
const X_POST_WEIGHT_MAX = 256;
const REVISION_MAX = 1000;
const APPROVAL_RECOVERY_LIMIT_MS = 360_000;

function initialProposalState(values: Proposal): ProposalState {
  return { values, confirming: false, submitting: false, generalError: null, fieldErrors: {}, success: null, revising: false, revision: "" };
}

function proposalReducer(state: ProposalState, action: ProposalAction): ProposalState {
  switch (action.type) {
    case "change": {
      const fieldErrors = { ...state.fieldErrors };
      delete fieldErrors[action.field];
      return {
        ...state,
        values: { ...state.values, [action.field]: action.field === "campaign_id" ? Number(action.value) : action.value },
        confirming: false,
        generalError: null,
        fieldErrors,
        success: null,
      };
    }
    case "reset": return initialProposalState(action.values);
    case "confirm": return { ...state, confirming: action.value, generalError: null };
    case "submit_started": return { ...state, submitting: true, generalError: null, fieldErrors: {} };
    case "submit_finished": return { ...state, submitting: false };
    case "error": return { ...state, generalError: action.general, fieldErrors: action.fields ?? state.fieldErrors };
    case "success": return { ...state, confirming: false, success: action.value };
    case "revision_open": return { ...state, revising: action.value, revision: action.value ? state.revision : "", generalError: null };
    case "revision": return { ...state, revision: action.value, generalError: null };
  }
}

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

function xWeightedLength(text: string) {
  let total = 0;
  for (const character of text.normalize("NFC")) {
    const code = character.codePointAt(0) ?? 0;
    total += code <= 4351 || (code >= 8192 && code <= 8205) || (code >= 8208 && code <= 8223) || (code >= 8242 && code <= 8247) ? 1 : 2;
  }
  return total;
}

function validLandingUrl(value: string) {
  if (/\s/.test(value)) return false;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") && Boolean(url.hostname) && !url.username && !url.password;
  } catch {
    return false;
  }
}

function validateProposal(campaign: boolean, values: Proposal) {
  const errors: Record<string, string> = {};
  if (campaign) {
    const proposal = values as CampaignProposal;
    const limits: Array<[keyof CampaignProposal, number, string]> = [
      ["title", CAMPAIGN_TITLE_MAX, "施策タイトル"],
      ["target_profile", CAMPAIGN_TEXT_MAX, "ターゲット像"],
      ["background", CAMPAIGN_TEXT_MAX, "実施背景"],
      ["objective", CAMPAIGN_TEXT_MAX, "施策目的"],
      ["plan", CAMPAIGN_TEXT_MAX, "施策内容"],
    ];
    for (const [field, max, label] of limits) {
      const value = String(proposal[field] ?? "");
      if (!value.trim()) errors[field] = `${label}を入力してください。`;
      else if (value.length > max) errors[field] = `${label}は${max.toLocaleString("ja-JP")}文字以内で入力してください。`;
    }
  } else {
    const proposal = values as XPostProposal;
    if (!Number.isSafeInteger(proposal.campaign_id) || proposal.campaign_id <= 0) errors.campaign_id = "施策IDは1以上の整数で入力してください。";
    if (!proposal.body.trim()) errors.body = "投稿本文を入力してください。";
    else if (/https?:\/\/[^\s]+/i.test(proposal.body)) errors.body = "投稿本文にURLを含めることはできません。";
    else if (xWeightedLength(proposal.body) > X_POST_WEIGHT_MAX) errors.body = `投稿本文はX換算で${X_POST_WEIGHT_MAX}文字以内にしてください。`;
    if (!proposal.landing_url.trim()) errors.landing_url = "遷移先URLを入力してください。";
    else if (proposal.landing_url.length > LANDING_URL_MAX) errors.landing_url = "遷移先URLは2,048文字以内で入力してください。";
    else if (!validLandingUrl(proposal.landing_url)) errors.landing_url = "httpまたはhttpsの正しいURLを入力してください。";
  }
  return errors;
}

function revisionMessage(campaign: boolean, values: Proposal, revision: string) {
  const fields = campaign
    ? `施策タイトル: ${(values as CampaignProposal).title}\nターゲット像: ${(values as CampaignProposal).target_profile}\n実施背景: ${(values as CampaignProposal).background}\n施策目的: ${(values as CampaignProposal).objective}\n施策内容: ${(values as CampaignProposal).plan}`
    : `施策ID: ${(values as XPostProposal).campaign_id}\n投稿本文: ${(values as XPostProposal).body}\n遷移先URL: ${(values as XPostProposal).landing_url}`;
  return `以下の現在の${campaign ? "施策案" : "X投稿案"}を、修正指示に従って見直してください。\n\n${fields}\n\n修正指示: ${revision.trim()}`;
}

function activityResult(status: ActivityStatus) {
  if (status === "succeeded") return "完了";
  if (status === "failed") return "失敗";
  return "安全のため停止";
}

type ActivityStatus = "succeeded" | "failed" | "blocked";

function CampaignCombobox({ disabled, error, idPrefix, onChange, onArchived, value }: {
  disabled: boolean;
  error?: string;
  idPrefix: number;
  onChange: (value: string) => void;
  onArchived: (message: string) => void;
  value: number;
}) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<CampaignListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [selectedTitle, setSelectedTitle] = useState(`施策ID ${value}`);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputId = `proposal-${idPrefix}-campaign_id`;
  const listId = `${inputId}-options`;
  const notifyArchived = useEffectEvent(onArchived);

  useEffect(() => {
    let active = true;
    void getCampaign(value).then(({ campaign }) => {
      if (!active) return;
      setSelectedTitle(campaign.title);
      if (campaign.archived_at) notifyArchived("この施策はアーカイブ済みのため、投稿先に選択できません。");
    }).catch(() => { /* The searchable list remains available if the current label cannot be restored. */ });
    return () => { active = false; };
  }, [value]);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setLoading(true);
      setSearchError("");
      void searchActiveCampaigns(query, controller.signal).then((response) => {
        setOptions(response.campaigns);
        setActiveIndex(response.campaigns.length > 0 ? 0 : -1);
      }).catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) setSearchError("施策を検索できませんでした。もう一度お試しください。");
      }).finally(() => setLoading(false));
    }, 300);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [query]);

  function select(option: CampaignListItem) {
    onChange(String(option.id));
    setSelectedTitle(option.title);
    setQuery(option.title);
    setOpen(false);
  }

  return (
    <div className={styles.campaignCombobox}>
      <label htmlFor={inputId}>対象施策</label>
      <input
        aria-activedescendant={open && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
        aria-autocomplete="list"
        aria-controls={listId}
        aria-describedby={error ? `${inputId}-error` : `${inputId}-status`}
        aria-expanded={open}
        aria-invalid={Boolean(error)}
        autoComplete="off"
        disabled={disabled}
        id={inputId}
        onBlur={() => window.setTimeout(() => setOpen(false), 100)}
        onChange={(event) => { setQuery(event.target.value); setOptions([]); setActiveIndex(-1); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && options.length > 0) { event.preventDefault(); setActiveIndex((current) => (current + 1) % options.length); }
          if (event.key === "ArrowUp" && options.length > 0) { event.preventDefault(); setActiveIndex((current) => (current <= 0 ? options.length - 1 : current - 1)); }
          if (event.key === "Enter" && open && activeIndex >= 0) { event.preventDefault(); select(options[activeIndex]); }
          if (event.key === "Escape") setOpen(false);
        }}
        placeholder="施策名で検索"
        role="combobox"
        type="search"
        value={query}
      />
      <p className={styles.selectedCampaign}>選択中: {selectedTitle}（ID {value}）</p>
      {open ? (
        <ul id={listId} role="listbox">
          {options.map((option, index) => <li aria-selected={index === activeIndex} id={`${listId}-${index}`} key={option.id} onClick={() => select(option)} onMouseDown={(event) => event.preventDefault()} role="option">{option.title}<span>ID {option.id}</span></li>)}
          {!loading && !searchError && options.length === 0 ? <li className={styles.comboboxMessage}>該当する施策がありません</li> : null}
        </ul>
      ) : null}
      <p aria-live="polite" className={styles.comboboxStatus} id={`${inputId}-status`}>{loading ? "施策を検索しています" : searchError || (open ? `${options.length}件の候補があります` : "")}</p>
      {error ? <small id={`${inputId}-error`}>{error}</small> : null}
    </div>
  );
}

function ProposalForm({ actionable, item, sessionId, audits, refreshHistory, sendRevision, sending }: {
  actionable: boolean;
  item: Extract<TurnItem, { type: "campaign_proposal" | "x_post_proposal" }>;
  sessionId: number;
  audits: ApprovalAudit[];
  refreshHistory: () => Promise<void>;
  sendRevision: (message: string) => Promise<void>;
  sending: boolean;
}) {
  const campaign = item.type === "campaign_proposal";
  const [state, proposalDispatch] = useReducer(proposalReducer, item.content, initialProposalState);
  const { values, confirming, submitting, generalError, fieldErrors, success, revising, revision } = state;
  const keyRef = useRef<{ signature: string; key: string } | null>(null);
  const approveButtonRef = useRef<HTMLButtonElement>(null);
  const cancelConfirmationRef = useRef<HTMLButtonElement>(null);
  const request = campaign ? campaignRequest(values as CampaignProposal) : values as XPostProposal;
  const signature = requestSignature(request as Record<string, unknown>);
  const operation = campaign ? "upsert_campaign" : "publish_x_post";
  const audit = audits.findLast((entry) => entry.state.operation === operation && requestSignature(entry.action.request) === signature);
  const unresolved = audit?.state.status === "outcome_unknown" || audit?.state.recovery === "manual_reconciliation";
  const externalSucceeded = audit?.state.external_succeeded === true;
  const completed = audit?.state.status === "succeeded";
  const retrySameKey = audit?.state.recovery === "retry_same_key";
  const processing = audit?.state.status === "processing";
  const archived = audit?.errorCode === "CAMPAIGN_ARCHIVED";
  const locked = !actionable || completed || unresolved || archived;
  const dirty = signature !== requestSignature(campaign ? campaignRequest(item.content as CampaignProposal) : item.content as XPostProposal);

  useEffect(() => {
    if (!dirty || locked) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    const warnBeforeNavigation = (event: MouseEvent) => {
      const target = event.target instanceof Element ? event.target.closest("a[href]") : null;
      if (target && !window.confirm("未保存の提案内容を破棄して移動しますか？")) event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    document.addEventListener("click", warnBeforeNavigation, true);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeUnload);
      document.removeEventListener("click", warnBeforeNavigation, true);
    };
  }, [dirty, locked]);

  useEffect(() => {
    if (!confirming) return;
    cancelConfirmationRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !submitting) {
        proposalDispatch({ type: "confirm", value: false });
        requestAnimationFrame(() => approveButtonRef.current?.focus());
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = cancelConfirmationRef.current?.closest('[role="alertdialog"]');
      const buttons = dialog ? Array.from(dialog.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")) : [];
      if (buttons.length === 0) return;
      const first = buttons[0];
      const last = buttons.at(-1) ?? first;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [confirming, submitting]);

  function update(field: string, value: string) {
    proposalDispatch({ type: "change", field, value });
  }

  async function submit() {
    if (submitting || locked) return;
    const validation = validateProposal(campaign, values);
    if (!campaign && fieldErrors.campaign_id?.includes("アーカイブ済み")) validation.campaign_id = fieldErrors.campaign_id;
    if (Object.keys(validation).length > 0) {
      proposalDispatch({ type: "error", general: "入力内容を確認してください。", fields: validation });
      requestAnimationFrame(() => document.getElementById(`proposal-${item.item_id}-${Object.keys(validation)[0]}`)?.focus());
      return;
    }
    proposalDispatch({ type: "submit_started" });
    let key = retrySameKey || processing ? audit?.action.id : undefined;
    if (audit?.state.status === "failed") {
      key = crypto.randomUUID();
      keyRef.current = { signature, key };
    } else if (!key) {
      if (keyRef.current?.signature !== signature) keyRef.current = { signature, key: crypto.randomUUID() };
      key = keyRef.current.key;
    }
    try {
      const recoveryStartedAt = Date.now();
      while (true) {
        try {
          if (campaign) {
            const result = await approveCampaign(sessionId, values as CampaignProposal, key);
            proposalDispatch({ type: "success", value: { message: "施策を承認して保存しました。", href: `/campaigns/${result.id}`, linkLabel: "施策の詳細を見る" } });
          } else {
            const result = await approveXPost(sessionId, values as XPostProposal, key);
            proposalDispatch({ type: "success", value: { message: externalSucceeded ? "公開済み投稿の保存を完了しました。" : "Xへの投稿を公開しました。", href: `/posts/${result.post_id}`, linkLabel: "投稿の詳細を見る" } });
          }
          break;
        } catch (error) {
          if (!(error instanceof ApiError) || error.code !== "IDEMPOTENCY_REQUEST_IN_PROGRESS") throw error;
          const waitMs = Math.max(1, error.retryAfterSeconds ?? 1) * 1000;
          if (Date.now() + waitMs - recoveryStartedAt > APPROVAL_RECOVERY_LIMIT_MS) throw error;
          proposalDispatch({ type: "error", general: "承認処理中です。完了後に同じ処理キーで結果を確認します。" });
          await new Promise((resolve) => window.setTimeout(resolve, waitMs));
        }
      }
    } catch (error) {
      if (error instanceof ApiError) {
        let message = error.code === "X_POST_OUTCOME_UNKNOWN"
          ? "Xへの公開結果を確認できません。再投稿せず、運用担当による照合をお待ちください。"
          : error.code === "X_POST_SAVE_FAILED"
            ? "Xへの公開は完了しています。再試行すると、同じ処理キーで保存だけを完了します。"
            : error.message;
        const validFields = new Set(campaign ? ["title", "target_profile", "background", "objective", "plan"] : ["campaign_id", "body", "landing_url"]);
        const fields = Object.fromEntries(error.fieldErrors.filter((entry) => entry.field && validFields.has(entry.field)).map((entry) => [entry.field as string, entry.message]));
        const summaries = error.fieldErrors.filter((entry) => entry.field === null || !validFields.has(entry.field)).map((entry) => entry.message);
        if (summaries.length > 0) message = summaries.join(" ");
        proposalDispatch({ type: "error", general: message, fields });
        const firstField = Object.keys(fields)[0];
        if (firstField) requestAnimationFrame(() => document.getElementById(`proposal-${item.item_id}-${firstField}`)?.focus());
      } else {
        proposalDispatch({ type: "error", general: "処理結果を確認できませんでした。同じ内容で再試行できます。" });
      }
    } finally {
      try { await refreshHistory(); } catch { /* Keep the actionable result visible if history refresh fails. */ }
      proposalDispatch({ type: "submit_finished" });
    }
  }

  function consultAgain() {
    if (!revision.trim()) {
      proposalDispatch({ type: "error", general: "修正指示を入力してください。" });
      return;
    }
    const message = revisionMessage(campaign, values, revision);
    if (message.length > 4000) {
      proposalDispatch({ type: "error", general: "現在の案と修正指示の合計が送信上限を超えています。内容を短くしてから再相談してください。" });
      return;
    }
    proposalDispatch({ type: "revision_open", value: false });
    void sendRevision(message);
  }

  const statusMessage = unresolved
    ? "公開結果を確認中です。二重投稿を防ぐため、この内容は再送できません。"
      : completed
        ? campaign ? "この施策は承認済みです。" : "この投稿は公開済みです。"
        : archived
          ? "この施策はアーカイブされたため変更できません。"
        : processing && !retrySameKey
          ? `${campaign ? "施策" : "X投稿"}の承認処理中です。完了するまで編集・再送できません。`
        : externalSucceeded
        ? "Xへの公開は完了しています。新しく投稿せず、保存処理だけを再試行できます。"
        : null;

  return (
    <article className={styles.proposalCard}>
      <header><span className={styles.proposalEyebrow}>{campaign ? "CAMPAIGN PROPOSAL" : "X POST PROPOSAL"}</span><h3>{campaign ? "施策案" : "X投稿案"}</h3><p>{actionable ? "内容を確認し、必要な箇所を直接編集できます。" : "同じ種類の新しい提案があるため、閲覧のみできます。"}</p></header>
      <div className={styles.proposalFields}>
        {campaign ? <>
          <ProposalField disabled={locked || processing || submitting} error={fieldErrors.title} idPrefix={item.item_id} label="施策タイトル" maxLength={CAMPAIGN_TITLE_MAX} name="title" onChange={update} value={(values as CampaignProposal).title} />
          <ProposalField disabled={locked || processing || submitting} error={fieldErrors.target_profile} idPrefix={item.item_id} label="ターゲット像" maxLength={CAMPAIGN_TEXT_MAX} multiline name="target_profile" onChange={update} value={(values as CampaignProposal).target_profile} />
          <ProposalField disabled={locked || processing || submitting} error={fieldErrors.background} idPrefix={item.item_id} label="実施背景" maxLength={CAMPAIGN_TEXT_MAX} multiline name="background" onChange={update} value={(values as CampaignProposal).background} />
          <ProposalField disabled={locked || processing || submitting} error={fieldErrors.objective} idPrefix={item.item_id} label="施策目的" maxLength={CAMPAIGN_TEXT_MAX} multiline name="objective" onChange={update} value={(values as CampaignProposal).objective} />
          <ProposalField disabled={locked || processing || submitting} error={fieldErrors.plan} idPrefix={item.item_id} label="施策内容" maxLength={CAMPAIGN_TEXT_MAX} multiline name="plan" onChange={update} value={(values as CampaignProposal).plan} />
        </> : <>
          <CampaignCombobox disabled={locked || processing || submitting} error={fieldErrors.campaign_id} idPrefix={item.item_id} onArchived={(message) => proposalDispatch({ type: "error", general: message, fields: { campaign_id: message } })} onChange={(value) => update("campaign_id", value)} value={(values as XPostProposal).campaign_id} />
          <ProposalField disabled={locked || processing || submitting} error={fieldErrors.body} idPrefix={item.item_id} label="投稿本文" maxLength={280} multiline name="body" onChange={update} value={(values as XPostProposal).body} />
          <ProposalField autoComplete="url" disabled={locked || processing || submitting} error={fieldErrors.landing_url} idPrefix={item.item_id} inputMode="url" label="遷移先URL" maxLength={LANDING_URL_MAX} name="landing_url" onChange={update} type="url" value={(values as XPostProposal).landing_url} />
          <span className={styles.characterCount}>{xWeightedLength((values as XPostProposal).body).toLocaleString("ja-JP")} / {X_POST_WEIGHT_MAX}（X換算・遷移先URL分を除く上限）</span>
        </>}
      </div>
      {dirty && !locked && !processing ? <div className={styles.proposalDirty} role="status"><span>未保存の変更があります。</span><button disabled={submitting} onClick={() => proposalDispatch({ type: "reset", values: item.content })} type="button">元の提案に戻す</button></div> : null}
      {statusMessage ? <p className={`${styles.approvalNotice} ${unresolved ? styles.approvalWarning : ""}`} role="status">{statusMessage}</p> : null}
      {generalError ? <p className={styles.proposalError} role="alert">{generalError}</p> : null}
      {success ? <p className={styles.proposalSuccess} role="status">{success.message} <Link href={success.href}>{success.linkLabel}</Link></p> : null}
      {actionable && !completed && !unresolved && !processing && !archived ? revising ? (
        <div className={styles.revisionBox}>
          <label htmlFor={`revision-${item.item_id}`}>AIへの修正指示</label>
          <textarea autoComplete="off" disabled={sending} id={`revision-${item.item_id}`} maxLength={REVISION_MAX} name="revision_instructions" onChange={(event) => proposalDispatch({ type: "revision", value: event.target.value })} placeholder="変更したい点を具体的に入力してください" required rows={3} value={revision} />
          <span>{revision.length.toLocaleString("ja-JP")} / {REVISION_MAX.toLocaleString("ja-JP")}</span>
          <div><button className={styles.secondaryButton} disabled={sending} onClick={() => proposalDispatch({ type: "revision_open", value: false })} type="button">キャンセル</button><button disabled={sending || !revision.trim()} onClick={consultAgain} type="button">{sending ? "送信中" : "現在の内容で再相談"}</button></div>
        </div>
      ) : <button className={styles.revisionButton} disabled={sending || submitting} onClick={() => proposalDispatch({ type: "revision_open", value: true })} type="button">AIに修正を相談</button> : null}
      {!locked ? confirming ? (
        <div className={styles.confirmBackdrop} role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !submitting) proposalDispatch({ type: "confirm", value: false }); }}>
          <section aria-describedby={`approval-description-${item.item_id}`} aria-labelledby={`approval-title-${item.item_id}`} aria-modal="true" className={styles.confirmApproval} role="alertdialog">
            <h4 id={`approval-title-${item.item_id}`}>{campaign ? "既存の施策を置き換えますか？" : "Xへ投稿を公開しますか？"}</h4>
            <p id={`approval-description-${item.item_id}`}>{campaign ? "既存の施策内容を、この提案の内容へ置き換えて保存します。" : externalSucceeded ? "Xへ再投稿せず、保存処理だけを再試行します。" : "Xへ公開され、公開後は変更・削除できません。"}</p>
            <div><button ref={cancelConfirmationRef} className={styles.secondaryButton} disabled={submitting} onClick={() => { proposalDispatch({ type: "confirm", value: false }); requestAnimationFrame(() => approveButtonRef.current?.focus()); }} type="button">戻る</button><button disabled={submitting} onClick={() => void submit()} type="button">{submitting ? "処理中…" : campaign ? "置き換えて保存" : externalSucceeded ? "保存を再試行" : "公開する"}</button></div>
          </section>
        </div>
      ) : <button ref={approveButtonRef} className={styles.approveButton} disabled={submitting || sending} onClick={() => processing || (campaign && (values as CampaignProposal).id === null) ? void submit() : proposalDispatch({ type: "confirm", value: true })} type="button">{processing ? "同じ処理キーで結果を確認" : campaign ? "承認して保存" : externalSucceeded ? "保存処理を再試行" : "承認して公開"}</button> : null}
    </article>
  );
}

function ProposalField({ autoComplete = "off", disabled, error, idPrefix, inputMode, label, maxLength, multiline = false, name, onChange, type = "text", value }: {
  autoComplete?: string; disabled: boolean; error?: string; idPrefix: number; inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"]; label: string; maxLength?: number; multiline?: boolean; name: string;
  onChange: (name: string, value: string) => void; type?: string; value: string;
}) {
  const id = `proposal-${idPrefix}-${name}`;
  return <label className={styles.proposalField} htmlFor={id}><span>{label}</span>{multiline
    ? <textarea aria-describedby={error ? `${id}-error` : undefined} aria-invalid={Boolean(error)} autoComplete={autoComplete} disabled={disabled} id={id} maxLength={maxLength} name={name} onChange={(event) => onChange(name, event.target.value)} required rows={3} value={value} />
    : <input aria-describedby={error ? `${id}-error` : undefined} aria-invalid={Boolean(error)} autoComplete={autoComplete} disabled={disabled} id={id} inputMode={inputMode} maxLength={maxLength} min={type === "number" ? 1 : undefined} name={name} onChange={(event) => onChange(name, event.target.value)} required type={type} value={value} />}{error ? <small id={`${id}-error`}>{error}</small> : null}</label>;
}

function Item({ actionable, item, sessionId, audits, refreshHistory, sendRevision, sending }: { actionable: boolean; item: TurnItem; sessionId: number; audits: ApprovalAudit[]; refreshHistory: () => Promise<void>; sendRevision: (message: string) => Promise<void>; sending: boolean }) {
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
    return <ProposalForm actionable={actionable} audits={audits} item={item} refreshHistory={refreshHistory} sendRevision={sendRevision} sending={sending} sessionId={sessionId} />;
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
    <div className={styles.notices} role={notices.some((notice) => notice.enforcement === "blocked") ? "alert" : "status"}>
      {[...grouped.values()].map(({ notice, count }) => (
        <p key={`${notice.event_type}:${notice.enforcement}`}>
          {noticeLabels[notice.event_type] ?? "安全性に関する通知があります"}{notice.enforcement === "blocked" ? "。安全のため処理を停止しました" : notice.enforcement === "sanitized" ? "。該当部分を除外して処理しました" : "。安全性を記録しました"}{count > 1 ? `（${count}件）` : ""}
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

function Turn({ turn, restore, sessionId, audits, latestProposalIds, refreshHistory, sendRevision, sending }: { turn: AgentTurn; restore: (message: string) => void; sessionId: number; audits: ApprovalAudit[]; latestProposalIds: Set<number>; refreshHistory: () => Promise<void>; sendRevision: (message: string) => Promise<void>; sending: boolean }) {
  const userText = turn.items.find((item) => item.type === "user_message");
  return (
    <li className={styles.turn}>
      {[...turn.items].sort((a, b) => a.item_number - b.item_number).map((item) => <Item actionable={latestProposalIds.has(item.item_id)} audits={audits} item={item} key={item.item_id} refreshHistory={refreshHistory} sendRevision={sendRevision} sending={sending} sessionId={sessionId} />)}
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
    return [{ action: action.content, state: turn.approval_state, errorCode: result?.content.error?.code ?? null }];
  });
  const latestByType = new Map<string, number>();
  for (const turn of state.turns) {
    for (const item of turn.items) {
      if (item.type === "campaign_proposal" || item.type === "x_post_proposal") latestByType.set(item.type, item.item_id);
    }
  }
  const latestProposalIds = new Set(latestByType.values());

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
          {state.turns.map((turn) => <Turn audits={audits} key={turn.agent_turn_id} latestProposalIds={latestProposalIds} refreshHistory={refreshHistory} restore={restore} sendRevision={send} sending={state.sending} sessionId={state.session?.session_id ?? 0} turn={turn} />)}
        </ol>
        {state.pendingMessage ? (
          <div className={styles.pendingTurn}>
            <article className={`${styles.message} ${styles.userMessage}`}>
              <span className={styles.speaker}>あなた</span><p>{state.pendingMessage}</p>
            </article>
            <div aria-live="polite" className={styles.progress} role="status">
              <span className={styles.speaker}>Hiromeru AI</span>
               <p><span aria-hidden="true" className={styles.spinner} />{state.recovering ? "結果を確認中" : activityLabels[state.activities.findLast((item) => item.status === "running")?.name ?? ""] ?? (state.activities.some((item) => item.status === "running") ? "処理を実行中" : "考えています")}</p>
               {state.activities.filter((item): item is typeof item & { status: ActivityStatus } => item.status !== "running").slice(-3).map((activity) => <small className={activity.status === "succeeded" ? undefined : styles.activityProblem} key={activity.activity_id} role={activity.status === "succeeded" ? undefined : "alert"}>{activityLabels[activity.name] ?? "処理"} {activityResult(activity.status)}</small>)}
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
          name="message"
          autoComplete="off"
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
