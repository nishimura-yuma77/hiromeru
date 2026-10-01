import Link from "next/link";

import type { CampaignOption } from "@/features/posts/api/searchCampaigns";
import type { PostListResponse, PostMetrics } from "@/features/posts/types/post";
import { postPageHref, type PostListParams } from "@/features/posts/utils/postParams";
import { MetricBar } from "@/shared/components/MetricBar/MetricBar";

import { PostFilters } from "./PostFilters";
import styles from "./PostList.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : dateFormat.format(date);
}

function PvMetric({ metrics, maxPv }: { metrics: PostMetrics; maxPv: number }) {
  if (metrics.status !== "completed") return <span aria-label="未計測">—</span>;
  return <div className={styles.pvMetric}>
    <span>{numberFormat.format(metrics.x_pv_count ?? 0)}</span>
    {maxPv > 0 ? <MetricBar value={metrics.x_pv_count ?? 0} max={maxPv} /> : null}
  </div>;
}

function LandingMetric({ metrics }: { metrics: PostMetrics }) {
  return metrics.status === "completed"
    ? <span className={styles.landingMetric}>{numberFormat.format(metrics.landing_user_count ?? 0)}</span>
    : <span aria-label="未計測">—</span>;
}

function PostBody({ post, returnTo }: { post: PostListResponse["posts"][number]; returnTo: string }) {
  const excerpt = post.body.slice(0, 60);
  return (
    <div className={styles.postBody}>
      <Link className={styles.body} href={`/posts/${post.post_id}?return_to=${returnTo}`} aria-label={`${formatDate(post.published_at)}の投稿「${excerpt}」の詳細を見る`}>{post.body}</Link>
      <div className={styles.postMeta}>
        <span>POST-{String(post.post_id).padStart(3, "0")}</span>
        <span className={post.metrics.status === "completed" ? styles.completedBadge : post.metrics.status === "pending" ? styles.pendingBadge : styles.failedBadge}>
          {post.metrics.status === "completed" ? "計測済み" : post.metrics.status === "pending" ? "計測待ち" : "計測失敗"}
        </span>
        {post.metrics.status === "pending" && post.metrics.scheduled_at ? <span>計測予定 {formatDate(post.metrics.scheduled_at)}</span> : null}
      </div>
    </div>
  );
}

function PublishInfo({ post }: { post: PostListResponse["posts"][number] }) {
  return (
    <div className={styles.publishInfo}>
      <Link href={`/campaigns/${post.campaign_id}`}>{post.campaign_title}</Link>
      {post.campaign_archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
      <time dateTime={post.published_at}>{formatDate(post.published_at)}</time>
    </div>
  );
}

export function PostList({ response, params, selectedCampaign }: { response: PostListResponse; params: PostListParams; selectedCampaign: CampaignOption | null }) {
  const currentListUrl = postPageHref(params, params.cursor || undefined);
  const hasFilters = Boolean(params.query || params.campaignId || params.publishedFrom || params.publishedTo);
  const maxCompletedPv = response.posts.reduce((max, post) => (
    post.metrics.status === "completed" ? Math.max(max, post.metrics.x_pv_count ?? 0) : max
  ), 0);

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <h1>投稿</h1>
      </header>

      <PostFilters key={`${params.query}:${params.campaignId ?? ""}:${params.sort}:${params.publishedFrom}:${params.publishedTo}`} params={params} selectedCampaign={selectedCampaign} />

      <section className={styles.results} aria-labelledby="post-results-title">
        <div className={params.query ? styles.resultHeading : styles.visuallyHidden}>
          <h2 id="post-results-title">{params.query ? `「${params.query}」に近い投稿` : "公開済み投稿"}</h2>
          {params.query ? <p>投稿本文をもとに関連度順で表示しています。</p> : null}
        </div>
        {response.posts.length === 0 ? (
          <div className={styles.empty}>
            <h3>{hasFilters ? "条件に合う投稿がありません" : "公開済みの投稿がありません"}</h3>
            <p>{hasFilters ? "検索語、施策ID、公開日の範囲を変更してください。" : "投稿案を承認すると、ここに表示されます。"}</p>
            <Link href={hasFilters ? "/posts" : "/chat/new"}>{hasFilters ? "条件をクリア" : "投稿案を相談する"}</Link>
          </div>
        ) : (
          <>
            <div className={styles.desktopTable}>
              <table>
                <caption className={styles.visuallyHidden}>公開済み投稿一覧</caption>
                <thead><tr><th scope="col">投稿</th><th scope="col">公開情報</th><th scope="col">初週PV</th><th scope="col">流入</th></tr></thead>
                <tbody>
                  {response.posts.map((post) => {
                    const returnTo = encodeURIComponent(currentListUrl);
                    return (
                      <tr key={post.post_id}>
                        <td><PostBody post={post} returnTo={returnTo} /></td>
                        <td><PublishInfo post={post} /></td>
                        <td><PvMetric metrics={post.metrics} maxPv={maxCompletedPv} /></td>
                        <td><LandingMetric metrics={post.metrics} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className={styles.mobileCards}>
              {response.posts.map((post) => {
                const returnTo = encodeURIComponent(currentListUrl);
                return (
                  <article className={styles.card} key={post.post_id}>
                    <PostBody post={post} returnTo={returnTo} />
                    <PublishInfo post={post} />
                    <dl className={styles.mobileMetrics}>
                      <div><dt>初週PV</dt><dd><PvMetric metrics={post.metrics} maxPv={maxCompletedPv} /></dd></div>
                      <div><dt>流入ユーザー</dt><dd><LandingMetric metrics={post.metrics} /></dd></div>
                    </dl>
                  </article>
                );
              })}
            </div>
          </>
        )}
        {!params.query && (params.cursor || response.next_cursor) ? (
          <nav className={styles.pagination} aria-label="投稿一覧のページ移動">
            {params.cursor ? <Link href={postPageHref(params)}>先頭へ</Link> : null}
            {response.next_cursor ? <Link href={postPageHref(params, response.next_cursor)}>次の20件</Link> : null}
          </nav>
        ) : null}
      </section>
    </main>
  );
}
