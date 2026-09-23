"use client";

import Link from "next/link";

import { useCampaignFormController } from "@/features/campaigns/controllers/useCampaignFormController";
import type { CampaignDetailResponse } from "@/features/campaigns/types/campaign";

import styles from "./CampaignDetail.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
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

export function CampaignDetail({ detail }: { detail: CampaignDetailResponse }) {
  const { campaign, metrics_summary: summary } = detail;
  const isArchived = campaign.archived_at !== null;
  const controller = useCampaignFormController(campaign);
  const rate = summary.landing_rate === null
    ? "—"
    : new Intl.NumberFormat("ja-JP", { style: "percent", maximumFractionDigits: 1 }).format(
        summary.landing_rate,
      );

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

      <section className={styles.summary} aria-labelledby="campaign-summary-title">
        <h2 id="campaign-summary-title">成果</h2>
        <dl>
          <div><dt>公開済み投稿</dt><dd>{numberFormat.format(summary.post_count)}件</dd></div>
          <div><dt>初週PV</dt><dd>{numberFormat.format(summary.x_pv_count)}</dd></div>
          <div><dt>流入ユーザー</dt><dd>{numberFormat.format(summary.landing_user_count)}</dd></div>
          <div><dt>流入率</dt><dd>{rate}</dd></div>
        </dl>
        <p className={styles.statusLine}>
          計測済み {summary.completed_count} / 待ち {summary.pending_count} / 失敗 {summary.failed_count}
        </p>
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
        {controller.state.isEditing ? (
          <form
            className={styles.editForm}
            onSubmit={(event) => {
              event.preventDefault();
              void controller.save();
            }}
          >
            {controller.state.error ? <p role="alert" className={styles.error}>{controller.state.error}</p> : null}
            <label>
              <span>施策タイトル</span>
              <input
                name="title"
                value={controller.state.form.title}
                onChange={(event) => controller.changeField("title", event.currentTarget.value)}
                maxLength={255}
                required
                disabled={controller.state.isPending}
              />
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
                />
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
          <div className={styles.relatedList}>
            {detail.posts.map((post) => (
              <article key={post.post_id}>
                <p className={styles.postBody}>{post.body}</p>
                <p><time dateTime={post.published_at}>{formatDate(post.published_at)} 公開</time></p>
                <p>{metricState(post.metrics)}</p>
                <Link href={`/posts/${post.post_id}`}>投稿の詳細を見る</Link>
              </article>
            ))}
          </div>
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
