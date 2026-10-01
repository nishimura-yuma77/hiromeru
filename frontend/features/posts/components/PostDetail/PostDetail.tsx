"use client";

import Link from "next/link";

import { Disclosure } from "@/shared/components/Disclosure/Disclosure";
import { usePostDetailQuery } from "@/features/posts/queries/postQueries";
import type { PostDetailResponse } from "@/features/posts/types/post";

import styles from "./PostDetail.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const segmenter = new Intl.Segmenter("ja-JP", { granularity: "grapheme" });
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo",
});

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : dateFormat.format(date);
}

export function PostDetail({ detail, returnTo }: { detail: PostDetailResponse; returnTo: string }) {
  const detailQuery = usePostDetailQuery(detail.post.post_id);
  const { post, campaign, metrics, tracking } = detailQuery.data ?? detail;
  const postNumber = `POST-${String(post.post_id).padStart(3, "0")}`;
  const statusLabel = metrics.status === "completed" ? "計測済み" : metrics.status === "pending" ? "計測待ち" : "計測失敗";
  const xPostUrl = /^\d+$/.test(post.x_post_id) ? `https://x.com/i/web/status/${post.x_post_id}` : null;

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.visuallyHidden}>投稿詳細</h1>
        <div>
          <Link className={styles.backLink} href={returnTo}>← 投稿一覧に戻る</Link>
          <div className={styles.headerMeta}>
            <span className={styles.postId}>{postNumber}</span>
            <span className={metrics.status === "completed" ? styles.completedBadge : metrics.status === "pending" ? styles.pendingBadge : styles.failedBadge}>{statusLabel}</span>
          </div>
        </div>
        <time className={styles.publishedAt} dateTime={post.published_at}>公開日時: {formatDate(post.published_at)}</time>
      </header>

      <div className={styles.body}>
        <section className={styles.panel} aria-labelledby="post-content-title">
          <h2 id="post-content-title">投稿本文</h2>
          <div className={styles.panelBody}>
            <p className={styles.postText}>{post.body}</p>
            <div className={styles.postFooter}>
              <span>{numberFormat.format(Array.from(segmenter.segment(post.body)).length)} 文字</span>
            </div>
          </div>
        </section>

        <section className={styles.panel} aria-labelledby="post-campaign-title">
          <h2 id="post-campaign-title">対象施策</h2>
          <div className={styles.panelBody}>
            <div className={styles.campaignLine}>
              <Link href={`/campaigns/${campaign.id}`}>{campaign.title}</Link>
              <span className={styles.recordId}>ID {campaign.id}</span>
              {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
            </div>
          </div>
        </section>

        <section className={styles.panel} aria-labelledby="post-metrics-title">
          <h2 id="post-metrics-title">計測結果</h2>
          <div className={styles.panelBody}>
            {metrics.status === "completed" ? (
              <>
                <dl className={styles.metricGrid}>
                  <div><dt>初週PV</dt><dd>{numberFormat.format(metrics.x_pv_count ?? 0)}</dd></div>
                  <div><dt>流入ユーザー</dt><dd>{numberFormat.format(metrics.landing_user_count ?? 0)}</dd></div>
                </dl>
                {metrics.measured_at ? <p className={styles.metricNote}><time dateTime={metrics.measured_at}>{formatDate(metrics.measured_at)} 計測</time></p> : null}
              </>
            ) : metrics.status === "pending" ? (
              <p className={styles.metricNote}>計測は公開後7日間で完了します。現在集計中です。{metrics.scheduled_at ? <> 計測予定: <time dateTime={metrics.scheduled_at}>{formatDate(metrics.scheduled_at)}</time></> : null}</p>
            ) : <p className={styles.metricNote}>計測に失敗しました。初週PVと流入ユーザー数は表示できません。</p>}
          </div>
        </section>

        <section className={styles.panel} aria-labelledby="post-tracking-title">
          <h2 id="post-tracking-title">Tracking情報</h2>
          <div className={styles.panelBody}>
            <div className={styles.urlField}>
              <span>遷移先URL</span>
              <div className={styles.urlRow}>
                <code>{tracking.landing_url}</code>
              </div>
            </div>
            <div className={styles.urlField}>
              <span>UTM付きURL</span>
              <div className={styles.urlRow}>
                <code>{tracking.tracked_url}</code>
              </div>
            </div>
            <div className={styles.utmSection}>
              <Disclosure defaultOpen summary="UTMパラメータ詳細">
                <dl className={styles.utmList}>
                  <div><dt>utm_source</dt><dd>{tracking.utm_source}</dd></div>
                  <div><dt>utm_medium</dt><dd>{tracking.utm_medium}</dd></div>
                  <div><dt>utm_campaign</dt><dd>{tracking.utm_campaign}</dd></div>
                  <div><dt>utm_content</dt><dd>{tracking.utm_content}</dd></div>
                </dl>
              </Disclosure>
            </div>
            <div className={styles.xPostRow}>
              <span>X投稿ID</span>
              <div>
                <code>{post.x_post_id}</code>
                {xPostUrl ? <a href={xPostUrl} target="_blank" rel="noopener noreferrer">Xで見る ↗<span className={styles.visuallyHidden}>（新しいタブで開く）</span></a> : <span>Xの投稿を開けません</span>}
              </div>
            </div>
          </div>
        </section>
        <Link className={styles.chatLink} href={`/chat/new?post_id=${post.post_id}&intent=discuss_post`}>この投稿について相談する →</Link>
      </div>
    </main>
  );
}
