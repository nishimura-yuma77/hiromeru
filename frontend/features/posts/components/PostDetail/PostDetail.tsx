"use client";

import Link from "next/link";

import { useCopyUrlController } from "@/features/posts/controllers/useCopyUrlController";
import type { PostDetailResponse } from "@/features/posts/types/post";

import styles from "./PostDetail.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "long",
  timeStyle: "short",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : dateFormat.format(date);
}

export function PostDetail({ detail, returnTo }: { detail: PostDetailResponse; returnTo: string }) {
  const { post, campaign, metrics, tracking } = detail;
  const copyController = useCopyUrlController();

  return (
    <main id="main-content" className={styles.page}>
      <Link className={styles.backLink} href={returnTo}>← 投稿一覧へ</Link>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Post {post.post_id}</p>
          <h1>投稿詳細</h1>
          <p><time dateTime={post.published_at}>{formatDate(post.published_at)} 公開</time></p>
        </div>
        <div className={styles.actions}>
          <a href={`https://x.com/i/web/status/${encodeURIComponent(post.x_post_id)}`} target="_blank" rel="noreferrer">Xで投稿を見る</a>
          <Link href={`/chat/new?post_id=${post.post_id}&intent=discuss_post`}>この投稿について相談する</Link>
        </div>
      </header>

      <div className={styles.overview}>
        <section className={styles.postContent} aria-labelledby="published-content-title">
          <h2 id="published-content-title">Xへ公開された内容</h2>
          <p>{post.body}</p>
          <a href={tracking.tracked_url} target="_blank" rel="noreferrer">{tracking.tracked_url}</a>
        </section>
        <aside className={styles.sidebar} aria-label="公開情報と初週計測">
          <section>
            <h2>公開情報</h2>
            <dl>
              <div>
                <dt>対象施策</dt>
                <dd><Link href={`/campaigns/${campaign.id}`}>{campaign.title}</Link></dd>
                {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
              </div>
              <div><dt>公開日時</dt><dd>{formatDate(post.published_at)}</dd></div>
              <div><dt>X投稿ID</dt><dd className={styles.mono}>{post.x_post_id}</dd></div>
            </dl>
          </section>
          <section>
            <h2>初週計測</h2>
            {metrics.status === "completed" ? (
              <dl className={styles.metricGrid}>
                <div><dt>初週PV</dt><dd>{numberFormat.format(metrics.x_pv_count ?? 0)}</dd></div>
                <div><dt>流入ユーザー</dt><dd>{numberFormat.format(metrics.landing_user_count ?? 0)}</dd></div>
              </dl>
            ) : (
              <p>{metrics.status === "pending" ? `計測待ち / ${formatDate(metrics.scheduled_at)}予定` : "計測に失敗しました"}</p>
            )}
            {metrics.measured_at ? <p><time dateTime={metrics.measured_at}>{formatDate(metrics.measured_at)} 計測</time></p> : null}
          </section>
        </aside>
      </div>

      <section className={styles.tracking} aria-labelledby="tracking-title">
        <div>
          <h2 id="tracking-title">トラッキング情報</h2>
          <p>投稿に設定された遷移先とUTMパラメータを確認できます。</p>
        </div>
        <div className={styles.urlRow}>
          <div><span>遷移先URL</span><code>{tracking.landing_url}</code></div>
          <button type="button" onClick={() => void copyController.copy("landing", tracking.landing_url)}>URLをコピー</button>
        </div>
        <div className={styles.urlRow}>
          <div><span>UTM付きURL</span><code>{tracking.tracked_url}</code></div>
          <button type="button" onClick={() => void copyController.copy("tracked", tracking.tracked_url)}>URLをコピー</button>
        </div>
        <details>
          <summary>UTMパラメータを見る</summary>
          <dl className={styles.utmList}>
            <div><dt>utm_source</dt><dd>{tracking.utm_source}</dd></div>
            <div><dt>utm_medium</dt><dd>{tracking.utm_medium}</dd></div>
            <div><dt>utm_campaign</dt><dd>{tracking.utm_campaign}</dd></div>
            <div><dt>utm_content</dt><dd>{tracking.utm_content}</dd></div>
          </dl>
        </details>
        <p className={styles.liveMessage} aria-live="polite">
          {copyController.state.error ?? (copyController.state.copiedField ? "URLをコピーしました。" : "")}
        </p>
      </section>
    </main>
  );
}
