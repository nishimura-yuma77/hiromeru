"use client";

import Link from "next/link";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/shared/components/Button/Button";
import { Disclosure } from "@/shared/components/Disclosure/Disclosure";
import { ListStatus } from "@/shared/components/ListStatus/ListStatus";
import { ListPageAction, ListPageLayout } from "@/shared/components/ListPageLayout/ListPageLayout";
import { useInvalidCursorRecovery, useQueryNavigation } from "@/shared/lib/useQueryNavigation";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import { useCampaignLabelQuery } from "@/features/campaigns/queries/campaignQueries";

import { useMemoryDeleteController } from "@/features/memories/controllers/useMemoryDeleteController";
import type {
  Memory,
  MemoryListResponse,
} from "@/features/memories/types/memory";
import type { CampaignOption } from "@/features/campaigns/queries/campaignKeys";
import { listMemoriesBrowser } from "@/features/memories/api/listMemoriesBrowser";
import { memoryKeys } from "@/features/memories/queries/memoryKeys";
import { useMemoryCampaignsInfiniteQuery, useMemoryListQuery, useMemoryPostsInfiniteQuery } from "@/features/memories/queries/memoryQueries";
import { memoryPageHref, parseMemoryListParams, type MemoryListParams } from "@/features/memories/utils/memoryParams";

import { CampaignFilter } from "./CampaignFilter";
import styles from "./MemoryList.module.scss";

const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "公開日不明" : dateFormat.format(date);
}

function RelatedCampaigns({ memory }: { memory: Memory }) {
  const query = useMemoryCampaignsInfiniteQuery(memory);
  const campaigns = query.data?.pages.flatMap((page) => page.campaigns) ?? memory.campaigns;

  return (
    <div className={styles.relationRow}>
      <span>関連施策:</span>
      {campaigns.length ? (
        <ul className={styles.campaignChips}>
          {campaigns.map((campaign) => (
            <li key={campaign.id}>
              <Link href={`/campaigns/${campaign.id}`}>{campaign.title}</Link>
              {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
            </li>
          ))}
        </ul>
      ) : <span>なし</span>}
      {query.hasNextPage ? (
        <Button variant="ghost" size="small" onClick={() => void query.fetchNextPage()} isLoading={query.isFetchingNextPage} loadingLabel="施策を読み込み中">施策をさらに表示</Button>
      ) : null}
      <p className={styles.relationStatus} role={query.error ? "alert" : "status"} aria-live="polite">
        {query.error ? "関連する施策を読み込めませんでした。" : query.isFetchingNextPage ? "関連する施策を読み込んでいます。" : ""}
      </p>
    </div>
  );
}

function RelatedPosts({ memory }: { memory: Memory }) {
  const query = useMemoryPostsInfiniteQuery(memory);
  const posts = query.data?.pages.flatMap((page) => page.posts) ?? memory.posts;
  const hasMore = query.hasNextPage;

  return (
    <div className={styles.postRelations}>
      {posts.length || hasMore ? (
        <Disclosure summary={`関連投稿: ${posts.length}件${hasMore ? "以上" : ""}`}>
          <ul>
            {posts.map((post) => (
              <li key={post.post_id}>
                <Link href={`/posts/${post.post_id}`}>{formatDate(post.published_at)}の投稿</Link>
              </li>
            ))}
          </ul>
          {hasMore ? (
            <Button variant="ghost" size="small" onClick={() => void query.fetchNextPage()} isLoading={query.isFetchingNextPage} loadingLabel="投稿を読み込み中">投稿をさらに表示</Button>
          ) : null}
          <p className={styles.relationStatus} role={query.error ? "alert" : "status"} aria-live="polite">
            {query.error ? "関連する投稿を読み込めませんでした。" : query.isFetchingNextPage ? "関連する投稿を読み込んでいます。" : ""}
          </p>
        </Disclosure>
      ) : <span>関連投稿: 0件</span>}
    </div>
  );
}

function parseMemorySearch(search: string) { return parseMemoryListParams(Object.fromEntries(new URLSearchParams(search))); }
function memoryHref(params: MemoryListParams) { return memoryPageHref(params, params.cursor || undefined); }
function withoutMemoryCursor(params: MemoryListParams) { return params.cursor ? { ...params, cursor: "" } : null; }

export function MemoryList({ response: initialResponse, selectedCampaign: initialCampaign }: { response: MemoryListResponse; params: MemoryListParams; selectedCampaign: CampaignOption | null }) {
  const [deletedIds, setDeletedIds] = useState<Set<number>>(() => new Set());
  const client = useQueryClient();
  const navigation = useQueryNavigation({
    parse: parseMemorySearch,
    key: memoryKeys.list,
    fetch: listMemoriesBrowser,
    href: memoryHref,
    withoutCursor: withoutMemoryCursor,
    fallbackError: "記憶を読み込めませんでした。",
  });
  const { params } = navigation;
  const query = useMemoryListQuery(params);
  useInvalidCursorRecovery(query.error, params, withoutMemoryCursor, navigation.apply);
  const label = useCampaignLabelQuery(params.campaignId, initialCampaign);
  const selectedCampaign = label.data ?? null;
  const rawResponse = query.data ?? initialResponse;
  const response = { ...rawResponse, memories: rawResponse.memories.filter((memory) => !deletedIds.has(memory.id)) };
  const loading = navigation.pending || query.isFetching;
  const error = navigation.pending ? "" : navigation.error || (query.error instanceof Error ? query.error.message : "");
  function load(nextParams: MemoryListParams, campaign?: CampaignOption | null) {
    if (campaign) client.setQueryData(campaignKeys.label(campaign.id), campaign);
    void navigation.apply(nextParams);
  }
  const controller = useMemoryDeleteController((memoryId) => {
    const index = response.memories.findIndex((memory) => memory.id === memoryId);
    const nextId = response.memories[index + 1]?.id ?? response.memories[index - 1]?.id;
    setDeletedIds((current) => new Set(current).add(memoryId));
    requestAnimationFrame(() => {
      (nextId ? document.getElementById(`memory-${nextId}`) : document.getElementById("memory-results-title"))?.focus();
    });
  });
  const selectedMemory = response.memories.find((memory) => memory.id === controller.state.selectedId);
  const visibleMemories = response.memories.filter((memory) => memory.id !== controller.state.deletedId);

  return (
    <ListPageLayout title="記憶" description="AIが参照する採用文脈の長期記憶" actions={<ListPageAction href="/chat/new">＋ 記憶の追加を相談する</ListPageAction>} filters={
      <section aria-labelledby="memory-search-title">
        <h2 id="memory-search-title" className={styles.visuallyHidden}>記憶を探す</h2>
        <CampaignFilter key={`${params.campaignId ?? ""}:${params.query}:${selectedCampaign?.title ?? ""}`} initialCampaign={selectedCampaign} query={params.query} onApply={load} />
      </section>
    }>

      <section className={styles.results} aria-labelledby="memory-results-title">
        <ListStatus loading={loading} error={error} onRetry={() => navigation.error ? navigation.retry() : void query.refetch()} loadingLabel="記憶を読み込んでいます" />
        <div className={params.query || params.campaignId ? styles.resultHeading : styles.visuallyHidden}>
          <h2 id="memory-results-title" tabIndex={-1}>{params.query ? `「${params.query}」に近い記憶` : params.campaignId ? `${selectedCampaign?.title ?? `施策ID ${params.campaignId}`} の記憶` : "蓄積した記憶"}</h2>
          {params.query ? <p>記憶の内容をもとに関連度順で表示しています。</p> : null}
        </div>

        {visibleMemories.length === 0 ? (
          <div className={styles.empty}>
            <h3>{params.query || params.campaignId ? "条件に合う記憶がありません" : "まだ記憶がありません"}</h3>
            <p>{params.query || params.campaignId ? "検索語や施策を変更してください。" : "投稿の計測が完了すると、結果から得た知見が蓄積されます。"}</p>
            {params.query || params.campaignId ? <Button variant="ghost" size="small" onClick={() => void load(parseMemoryListParams({}), null)}>検索条件をクリア</Button> : null}
          </div>
        ) : (
          <div className={styles.list}>
            {visibleMemories.map((memory) => (
              <article className={styles.card} id={`memory-${memory.id}`} key={memory.id} tabIndex={-1}>
                <p className={styles.memoryText}>{memory.content}</p>
                <Button variant="ghost" size="small" aria-label={`記憶ID ${memory.id}を削除する`} onClick={() => controller.open(memory.id)}>削除</Button>
                <div className={styles.related}>
                  <RelatedCampaigns memory={memory} />
                  <RelatedPosts memory={memory} />
                </div>
                <p className={styles.recordId}>MEM-{String(memory.id).padStart(3, "0")}</p>
              </article>
            ))}
          </div>
        )}

        {!params.query && (params.cursor || response.next_cursor) ? (
          <nav className={styles.pagination} aria-label="記憶一覧のページ移動">
            {params.cursor ? <Button variant="ghost" size="small" disabled={loading} onClick={() => void load({ ...params, cursor: "" }, selectedCampaign)}>先頭へ</Button> : null}
            {response.next_cursor ? <Button variant="ghost" size="small" disabled={loading} onClick={() => void load({ ...params, cursor: response.next_cursor ?? "" }, selectedCampaign)}>次の20件</Button> : null}
          </nav>
        ) : null}
      </section>

      {selectedMemory ? (
        <div className={styles.dialogBackdrop} role="presentation">
          <section className={styles.dialog} role="alertdialog" aria-modal="true" aria-labelledby="delete-memory-title" aria-describedby="delete-memory-description">
            <p className={styles.eyebrow}>Delete memory</p>
            <h2 id="delete-memory-title">この記憶を削除しますか？</h2>
            <p id="delete-memory-description">削除した記憶は元に戻せません。関連する施策と投稿自体は削除されません。</p>
            <blockquote>{selectedMemory.content}</blockquote>
            {controller.state.error ? <p className={styles.error} role="alert">{controller.state.error}</p> : null}
            <div className={styles.dialogActions}>
              <Button variant="secondary" onClick={controller.close} disabled={controller.state.isPending} autoFocus>キャンセル</Button>
              <Button variant="danger" onClick={() => void controller.confirmDelete()} isLoading={controller.state.isPending} loadingLabel="削除中">削除する</Button>
            </div>
          </section>
        </div>
      ) : null}
      <p className={styles.liveMessage} aria-live="polite">{controller.state.deletedId ? "記憶を削除しました。" : ""}</p>
    </ListPageLayout>
  );
}
