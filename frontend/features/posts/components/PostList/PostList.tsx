import Link from "next/link";

import type { PostListResponse, PostMetrics } from "@/features/posts/types/post";
import { postPageHref, type PostListParams } from "@/features/posts/utils/postParams";

import styles from "./PostList.module.scss";

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

function Metric({ metrics }: { metrics: PostMetrics }) {
  if (metrics.status === "completed") {
    return (
      <dl className={styles.metricValues}>
        <div><dt>初週PV</dt><dd>{numberFormat.format(metrics.x_pv_count ?? 0)}</dd></div>
        <div><dt>流入ユーザー</dt><dd>{numberFormat.format(metrics.landing_user_count ?? 0)}</dd></div>
      </dl>
    );
  }
  return (
    <p className={styles.metricStatus}>
      {metrics.status === "pending" ? `計測待ち / ${formatDate(metrics.scheduled_at)}予定` : "計測に失敗しました"}
    </p>
  );
}

export function PostList({ response, params }: { response: PostListResponse; params: PostListParams }) {
  const currentListUrl = postPageHref(params, params.cursor || undefined);
  const hasFilters = Boolean(params.query || params.campaignId || params.publishedFrom || params.publishedTo);

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Published work</p>
          <h1>投稿</h1>
          <p>Xへ公開済みの投稿と初週の成果を確認できます。</p>
        </div>
        <Link className={styles.primaryLink} href="/chat/new">投稿案を相談する</Link>
      </header>

      <section className={styles.filters} aria-labelledby="post-filter-title">
        <h2 id="post-filter-title">投稿を探す</h2>
        <form action="/posts" method="get" className={styles.filterForm}>
          <label className={styles.searchField}>
            <span>投稿を検索</span>
            <input type="search" name="query" defaultValue={params.query} maxLength={1000} placeholder="投稿本文を自然な言葉で検索" />
          </label>
          <label>
            <span>施策ID</span>
            <input type="text" inputMode="numeric" pattern="[1-9][0-9]*" name="campaign_id" defaultValue={params.campaignId ?? ""} />
          </label>
          <label>
            <span>公開日の開始</span>
            <input type="date" name="published_from" defaultValue={params.publishedFrom} />
          </label>
          <label>
            <span>公開日の終了</span>
            <input type="date" name="published_to" defaultValue={params.publishedTo} />
          </label>
          <label>
            <span>並び順</span>
            <select name="sort" defaultValue={params.sort} disabled={Boolean(params.query)}>
              <option value="published_at_desc">公開日時の新しい順</option>
              <option value="published_at_asc">公開日時の古い順</option>
              <option value="x_pv_count_desc">初週PVの多い順</option>
              <option value="x_pv_count_asc">初週PVの少ない順</option>
            </select>
          </label>
          <div className={styles.filterActions}>
            <button type="submit">条件を適用</button>
            <Link href="/posts">条件をクリア</Link>
          </div>
        </form>
        {params.query ? <p className={styles.hint}>検索中は関連度順で表示し、並び替えは利用できません。</p> : null}
      </section>

      <section aria-labelledby="post-results-title">
        <div className={styles.resultHeading}>
          <div>
            <p className={styles.eyebrow}>Results</p>
            <h2 id="post-results-title">{params.query ? `「${params.query}」に近い投稿` : "公開済み投稿"}</h2>
          </div>
          <p>{params.query ? "投稿本文をもとに関連度順で表示しています。" : "20件ずつ表示"}</p>
        </div>
        {response.posts.length === 0 ? (
          <div className={styles.empty}>
            <h3>{hasFilters ? "条件に合う投稿がありません" : "公開済みの投稿がありません"}</h3>
            <p>{hasFilters ? "検索語、施策ID、公開日の範囲を変更してください。" : "投稿案を承認すると、ここに表示されます。"}</p>
            <Link href={hasFilters ? "/posts" : "/chat/new"}>{hasFilters ? "条件をクリア" : "投稿案を相談する"}</Link>
          </div>
        ) : (
          <div className={styles.list}>
            {response.posts.map((post) => {
              const returnTo = encodeURIComponent(currentListUrl);
              return (
                <article className={styles.card} key={post.post_id}>
                  <div>
                    <p className={styles.body}>{post.body}</p>
                    <Link href={`/posts/${post.post_id}?return_to=${returnTo}`} aria-label={`${formatDate(post.published_at)}の投稿の詳細を見る`}>詳細を見る</Link>
                  </div>
                  <div className={styles.publishInfo}>
                    <Link href={`/campaigns/${post.campaign_id}`}>{post.campaign_title}</Link>
                    {post.campaign_archived_at ? <span className={styles.archivedBadge}>施策はアーカイブ済み</span> : null}
                    <time dateTime={post.published_at}>{formatDate(post.published_at)} 公開</time>
                  </div>
                  <Metric metrics={post.metrics} />
                </article>
              );
            })}
          </div>
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
