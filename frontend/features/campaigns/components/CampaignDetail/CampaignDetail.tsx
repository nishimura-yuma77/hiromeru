"use client";

import Link from "next/link";

import { useCampaignFormController } from "@/features/campaigns/controllers/useCampaignFormController";
import type { CampaignDetailResponse } from "@/features/campaigns/types/campaign";
import type { CampaignField } from "@/features/campaigns/state/campaignFormReducer";

import styles from "./CampaignDetail.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const campaignFieldLabels: Record<CampaignField, string> = {
  title: "施策タイトル",
  target_profile: "ターゲット像",
  background: "実施背景",
  objective: "施策目的",
  plan: "施策内容",
};
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : dateFormat.format(date);
}

function metricState(metrics: CampaignDetailResponse["posts"][number]["metrics"]): string {
  if (metrics.status === "completed") {
    return `初週PV ${numberFormat.format(metrics.x_pv_count ?? 0)} / 流入ユーザー ${numberFormat.format(metrics.landing_user_count ?? 0)}`;
  }
  if (metrics.status === "pending") return `計測待ち / ${formatDate(metrics.scheduled_at)}予定`;
  return "計測に失敗しました";
}

function summaryExplanation(summary: CampaignDetailResponse["metrics_summary"]): string {
  const excluded = Math.max(
    0,
    summary.post_count - summary.completed_count - summary.pending_count - summary.failed_count,
  );
  if (summary.post_count === 0) return "公開済み投稿がないため、成果はまだ集計されていません。";
  if (summary.completed_count === 0 && summary.pending_count > 0) {
    return "計測待ちの投稿があります。計測完了後に初週PVと流入が表示されます。";
  }
  if (summary.completed_count === 0 && summary.failed_count > 0) {
    return "計測結果を取得できなかったため、成果を表示できません。";
  }
  if (summary.completed_count === 0 && excluded > 0) {
    return "公開済み投稿はすべて計測対象外です。";
  }
  if (summary.pending_count > 0 || summary.failed_count > 0 || excluded > 0) {
    return "計測済みの投稿だけを成果に集計しています。";
  }
  return "すべての公開済み投稿を集計した成果です。";
}

function PvBar({ value, max }: { value: number | null; max: number }) {
  const width = value === null || max <= 0 ? 0 : (value / max) * 100;
  return (
    <span className={styles.pvTrack} aria-hidden="true">
      <span className={styles.pvFill} style={{ width: `${width}%` }} />
    </span>
  );
}

export function CampaignDetail({ detail }: { detail: CampaignDetailResponse }) {
  const { campaign, metrics_summary: summary } = detail;
  const controller = useCampaignFormController(campaign);
  const isArchived = campaign.archived_at !== null || (controller.state.conflictCampaign?.archived_at ?? null) !== null;
  const hasCompletedMetrics = summary.completed_count > 0;
  const rate = !hasCompletedMetrics || summary.landing_rate === null
    ? "—"
    : new Intl.NumberFormat("ja-JP", { style: "percent", maximumFractionDigits: 1 }).format(
        summary.landing_rate,
      );
  const maxCompletedPv = detail.posts.reduce(
    (max, post) => post.metrics.status === "completed"
      ? Math.max(max, post.metrics.x_pv_count ?? 0)
      : max,
    0,
  );
  const conflictFields = controller.state.conflictCampaign
    ? (Object.keys(campaignFieldLabels) as CampaignField[]).filter(
        (field) => controller.state.form[field] !== controller.state.baseline[field],
      )
    : [];

  return (
    <main id="main-content" className={styles.page}>
      <Link className={styles.backLink} href="/campaigns">← 施策一覧へ</Link>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Campaign {campaign.id}</p>
          {isArchived ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
          <h1>{campaign.title}</h1>
          <p>
            <time dateTime={campaign.created_at}>作成 {formatDate(campaign.created_at)}</time>
            {" / "}
            <time dateTime={campaign.updated_at}>更新 {formatDate(campaign.updated_at)}</time>
          </p>
        </div>
        {!isArchived ? <div className={styles.headerActions}>
          <Link href={`/chat/new?campaign_id=${campaign.id}&intent=create_post`}>
            この施策で投稿案を作る
          </Link>
          <Link href={`/chat/new?campaign_id=${campaign.id}&intent=revise_campaign`}>
            変更を相談する
          </Link>
        </div> : null}
      </header>

      {isArchived ? (
        <p className={styles.archivedNotice}>
          この施策はアーカイブ済みです。内容の編集や、この施策を使った投稿案の作成はできません。過去の内容と成果は引き続き確認できます。
        </p>
      ) : null}

      <section className={styles.summary} aria-labelledby="campaign-summary-title">
        <h2 id="campaign-summary-title">成果</h2>
        <dl>
          <div><dt>公開済み投稿</dt><dd>{numberFormat.format(summary.post_count)}件</dd></div>
          <div><dt>初週PV</dt><dd>{hasCompletedMetrics ? numberFormat.format(summary.x_pv_count) : "—"}</dd></div>
          <div><dt>流入ユーザー</dt><dd>{hasCompletedMetrics ? numberFormat.format(summary.landing_user_count) : "—"}</dd></div>
          <div><dt>流入率</dt><dd>{rate}</dd></div>
        </dl>
        <p className={styles.statusLine}>{summaryExplanation(summary)}</p>
        <div className={styles.summaryStatuses} aria-label="計測状況">
          {summary.completed_count > 0 ? <span>計測済み {summary.completed_count}</span> : null}
          {summary.pending_count > 0 ? <span>待ち {summary.pending_count}</span> : null}
          {summary.failed_count > 0 ? <span>失敗 {summary.failed_count}</span> : null}
          {summary.post_count - summary.completed_count - summary.pending_count - summary.failed_count > 0
            ? <span>対象外 {summary.post_count - summary.completed_count - summary.pending_count - summary.failed_count}</span>
            : null}
        </div>
      </section>

      <section className={styles.section} aria-labelledby="campaign-content-title">
        <div className={styles.sectionHeading}>
          <h2 id="campaign-content-title">施策内容</h2>
          {!isArchived && !controller.state.isEditing ? (
            <button type="button" onClick={controller.startEditing}>編集</button>
          ) : controller.state.isEditing ? (
            <span>編集中</span>
          ) : <span className={styles.readOnly}>読み取り専用</span>}
        </div>
        {controller.state.isEditing && !isArchived ? (
          <form
            className={styles.editForm}
            onSubmit={(event) => {
              event.preventDefault();
              void controller.save();
            }}
          >
            {controller.state.error ? (
              <div role="alert" className={controller.state.hasConflict ? styles.conflict : styles.error}>
                <p>{controller.state.error}</p>
                {controller.state.hasConflict ? (
                  controller.state.conflictCampaign ? <>
                    <button type="button" onClick={controller.toggleConflictComparison}>最新内容との差分を確認</button>
                    {controller.state.showConflictComparison ? (
                      <div className={styles.conflictComparison}>
                        {conflictFields.map((field) => (
                          <section key={field}>
                            <h3>{campaignFieldLabels[field]}</h3>
                            <div><div><strong>最新の保存内容</strong><p>{controller.state.conflictCampaign?.[field]}</p></div><div><strong>あなたの入力</strong><p>{controller.state.form[field]}</p></div></div>
                          </section>
                        ))}
                        <div className={styles.conflictActions}>
                          <button type="button" onClick={controller.applyLatest}>最新内容をフォームへ反映</button>
                          <button type="button" onClick={controller.keepDraft}>現在の入力を優先して編集を続ける</button>
                        </div>
                      </div>
                    ) : null}
                  </> : <span>最新内容を読み込めませんでした。時間をおいてもう一度お試しください。</span>
                ) : null}
              </div>
            ) : null}
            <label>
              <span>施策タイトル</span>
              <input
                name="title"
                value={controller.state.form.title}
                onChange={(event) => controller.changeField("title", event.currentTarget.value)}
                maxLength={255}
                required
                disabled={controller.state.isPending}
                aria-invalid={Boolean(controller.state.fieldErrors.title)}
                aria-describedby={controller.state.fieldErrors.title ? "campaign-title-error" : undefined}
              />
              {controller.state.fieldErrors.title ? (
                <span id="campaign-title-error" className={styles.fieldError}>{controller.state.fieldErrors.title}</span>
              ) : null}
            </label>
            {([
              ["target_profile", "ターゲット像"],
              ["background", "実施背景"],
              ["objective", "施策目的"],
              ["plan", "施策内容"],
            ] as const).map(([field, label]) => (
              <label key={field}>
                <span>{label}</span>
                <textarea
                  name={field}
                  value={controller.state.form[field]}
                  onChange={(event) => controller.changeField(field, event.currentTarget.value)}
                  maxLength={10000}
                  required
                  disabled={controller.state.isPending}
                  rows={4}
                  aria-invalid={Boolean(controller.state.fieldErrors[field])}
                  aria-describedby={controller.state.fieldErrors[field] ? `campaign-${field}-error` : undefined}
                />
                {controller.state.fieldErrors[field] ? (
                  <span id={`campaign-${field}-error`} className={styles.fieldError}>{controller.state.fieldErrors[field]}</span>
                ) : null}
              </label>
            ))}
            <p>この編集はAgentとの会話履歴には保存されません。</p>
            <div className={styles.formActions}>
              <button type="button" onClick={controller.cancel} disabled={controller.state.isPending}>取消</button>
              <button type="submit" disabled={!controller.canSave}>
                {controller.state.isPending ? "保存中" : "変更内容を保存"}
              </button>
            </div>
          </form>
        ) : (
          <dl className={styles.contentList}>
            <div><dt>ターゲット像</dt><dd>{campaign.target_profile}</dd></div>
            <div><dt>実施背景</dt><dd>{campaign.background}</dd></div>
            <div><dt>施策目的</dt><dd>{campaign.objective}</dd></div>
            <div><dt>施策内容</dt><dd>{campaign.plan}</dd></div>
          </dl>
        )}
        <p className={styles.liveMessage} aria-live="polite">
          {controller.state.isSaved ? "施策を更新しました。" : ""}
        </p>
      </section>

      <section className={styles.section} aria-labelledby="campaign-posts-title">
        <div className={styles.sectionHeading}>
          <h2 id="campaign-posts-title">公開済み投稿</h2>
          {summary.post_count > 0 ? <Link href={`/posts?campaign_id=${campaign.id}`}>すべての投稿を見る</Link> : null}
        </div>
        {detail.posts.length ? (
          <>
            <div className={styles.relatedTableWrap}>
              <table className={styles.relatedTable}>
                <thead><tr><th scope="col">投稿</th><th scope="col">公開日</th><th scope="col">初週PV</th><th scope="col">計測状況</th></tr></thead>
                <tbody>
                  {detail.posts.map((post) => (
                    <tr key={post.post_id}>
                      <th scope="row"><Link href={`/posts/${post.post_id}`}>{post.body}</Link></th>
                      <td><time dateTime={post.published_at}>{formatDate(post.published_at)}</time></td>
                      <td>
                        {post.metrics.status === "completed" ? numberFormat.format(post.metrics.x_pv_count ?? 0) : "—"}
                        {maxCompletedPv > 0 && post.metrics.status === "completed" ? <PvBar value={post.metrics.x_pv_count} max={maxCompletedPv} /> : null}
                      </td>
                      <td>{metricState(post.metrics)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.relatedCards}>
              {detail.posts.map((post) => (
                <article key={post.post_id}>
                  <p className={styles.postBody}>{post.body}</p>
                  <p><time dateTime={post.published_at}>{formatDate(post.published_at)} 公開</time></p>
                  <p>{metricState(post.metrics)}</p>
                  {post.metrics.status === "completed" && maxCompletedPv > 0 ? (
                    <PvBar value={post.metrics.x_pv_count} max={maxCompletedPv} />
                  ) : null}
                  <Link href={`/posts/${post.post_id}`}>投稿の詳細を見る</Link>
                </article>
              ))}
            </div>
            {maxCompletedPv <= 0 ? <p className={styles.emptyText}>計測できた投稿がまだありません</p> : null}
          </>
        ) : <p className={styles.emptyText}>公開済みの投稿はありません。</p>}
      </section>

      <section className={styles.section} aria-labelledby="campaign-memories-title">
        <div className={styles.sectionHeading}>
          <h2 id="campaign-memories-title">関連する記憶</h2>
          {detail.has_more_memories ? <Link href={`/memories?campaign_id=${campaign.id}`}>記憶一覧を見る</Link> : null}
        </div>
        {detail.memories.length ? (
          <ul className={styles.memoryList}>
            {detail.memories.map((memory) => <li key={memory.id}>{memory.content}</li>)}
          </ul>
        ) : <p className={styles.emptyText}>この施策に関連する記憶はありません。</p>}
      </section>
    </main>
  );
}
