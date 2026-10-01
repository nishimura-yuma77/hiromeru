"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";

import type { CampaignOption } from "@/features/campaigns/queries/campaignKeys";
import { listPostsBrowser } from "@/features/posts/api/listPostsBrowser";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import { useCampaignLabelQuery } from "@/features/campaigns/queries/campaignQueries";
import type { PostListResponse, PostMetrics } from "@/features/posts/types/post";
import { parsePostListParams, postPageHref, type PostListParams } from "@/features/posts/utils/postParams";
import { postKeys } from "@/features/posts/queries/postKeys";
import { usePostListQuery } from "@/features/posts/queries/postQueries";
import { Button } from "@/shared/components/Button/Button";
import { ListStatus } from "@/shared/components/ListStatus/ListStatus";
import { ListPageAction, ListPageLayout } from "@/shared/components/ListPageLayout/ListPageLayout";
import { MetricBar } from "@/shared/components/MetricBar/MetricBar";
import { useInvalidCursorRecovery, useQueryNavigation } from "@/shared/lib/useQueryNavigation";

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

function parsePostSearch(search: string) {
  return parsePostListParams(Object.fromEntries(new URLSearchParams(search)));
}

function postHref(params: PostListParams) {
  return postPageHref(params, params.cursor || undefined);
}
function withoutPostCursor(params: PostListParams) { return params.cursor ? { ...params, cursor: "" } : null; }

export function PostList({ response: initialResponse, selectedCampaign: initialCampaign }: { response: PostListResponse; params: PostListParams; selectedCampaign: CampaignOption | null }) {
  const client = useQueryClient();
  const navigation = useQueryNavigation({
    parse: parsePostSearch,
    key: postKeys.list,
    fetch: listPostsBrowser,
    href: postHref,
    withoutCursor: withoutPostCursor,
    fallbackError: "投稿を読み込めませんでした。",
  });
  const { params } = navigation;
  const query = usePostListQuery(params);
  useInvalidCursorRecovery(query.error, params, withoutPostCursor, navigation.apply);
  const label = useCampaignLabelQuery(params.campaignId, initialCampaign);
  const selectedCampaign: CampaignOption | null = label.data
    ? { id: label.data.id, title: label.data.title, archived_at: label.data.archived_at ?? null } : null;
  const response = query.data ?? initialResponse;
  const loading = navigation.pending || query.isFetching;
  const error = navigation.pending ? "" : navigation.error || (query.error instanceof Error ? query.error.message : "");
  function apply(nextParams: PostListParams, campaign?: CampaignOption | null) {
    if (campaign) client.setQueryData(campaignKeys.label(campaign.id), campaign);
    void navigation.apply(nextParams);
  }

  const currentListUrl = postPageHref(params, params.cursor || undefined);
  const hasFilters = Boolean(params.query || params.campaignId || params.publishedFrom || params.publishedTo);
  const maxCompletedPv = response.posts.reduce((max, post) => (
    post.metrics.status === "completed" ? Math.max(max, post.metrics.x_pv_count ?? 0) : max
  ), 0);

  return (
    <ListPageLayout title="投稿" actions={<ListPageAction href="/chat/new">＋ 投稿案を相談する</ListPageAction>} filters={
      <PostFilters key={`${params.query}:${params.campaignId ?? ""}:${params.sort}:${params.publishedFrom}:${params.publishedTo}:${selectedCampaign?.title ?? ""}`} params={params} selectedCampaign={selectedCampaign} onApply={apply} />
    }>

      <section className={styles.results} aria-labelledby="post-results-title">
        <ListStatus loading={loading} error={error} onRetry={() => navigation.error ? navigation.retry() : void query.refetch()} loadingLabel="投稿を読み込んでいます" />
        <div className={params.query ? styles.resultHeading : styles.visuallyHidden}>
          <h2 id="post-results-title">{params.query ? `「${params.query}」に近い投稿` : "公開済み投稿"}</h2>
          {params.query ? <p>投稿本文をもとに関連度順で表示しています。</p> : null}
        </div>
        {response.posts.length === 0 ? (
          <div className={styles.empty}>
            <h3>{hasFilters ? "条件に合う投稿がありません" : "公開済みの投稿がありません"}</h3>
            <p>{hasFilters ? "検索語、施策ID、公開日の範囲を変更してください。" : "投稿案を承認すると、ここに表示されます。"}</p>
            {hasFilters ? <Button variant="ghost" size="small" onClick={() => void navigation.apply(parsePostListParams({}))}>条件をクリア</Button> : <Link href="/chat/new">投稿案を相談する</Link>}
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
            {params.cursor ? <Button variant="ghost" size="small" disabled={loading} onClick={() => apply({ ...params, cursor: "" })}>先頭へ</Button> : null}
            {response.next_cursor ? <Button variant="ghost" size="small" disabled={loading} onClick={() => apply({ ...params, cursor: response.next_cursor ?? "" })}>次の20件</Button> : null}
          </nav>
        ) : null}
      </section>
    </ListPageLayout>
  );
}
