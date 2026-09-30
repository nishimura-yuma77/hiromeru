"use client";

import Link from "next/link";
import { useState } from "react";

import {
  listMemoryCampaigns,
  listMemoryPosts,
} from "@/features/memories/api/listMemoryRelations";
import { useMemoryDeleteController } from "@/features/memories/controllers/useMemoryDeleteController";
import type {
  Memory,
  MemoryCampaign,
  MemoryListResponse,
  MemoryPost,
} from "@/features/memories/types/memory";
import type { CampaignOption } from "@/features/memories/api/searchCampaigns";
import { memoryPageHref, type MemoryListParams } from "@/features/memories/utils/memoryParams";

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
  const [campaigns, setCampaigns] = useState<MemoryCampaign[]>(memory.campaigns);
  const [cursor, setCursor] = useState(memory.campaigns_next_cursor);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMore() {
    if (!cursor || isLoading) return;
    setIsLoading(true);
    setError("");
    try {
      const response = await listMemoryCampaigns(memory.id, cursor);
      setCampaigns((current) => [...current, ...response.campaigns]);
      setCursor(response.next_cursor);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "関連する施策を読み込めませんでした。");
    } finally {
      setIsLoading(false);
    }
  }

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
      {cursor ? (
        <button className={styles.loadMore} type="button" onClick={() => void loadMore()} disabled={isLoading}>
          {isLoading ? "読み込み中" : "施策をさらに表示"}
        </button>
      ) : null}
      <p className={styles.relationStatus} role={error ? "alert" : "status"} aria-live="polite">
        {error || (isLoading ? "関連する施策を読み込んでいます。" : "")}
      </p>
    </div>
  );
}

function RelatedPosts({ memory }: { memory: Memory }) {
  const [posts, setPosts] = useState<MemoryPost[]>(memory.posts);
  const [cursor, setCursor] = useState(memory.posts_next_cursor);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadMore() {
    if (!cursor || isLoading) return;
    setIsLoading(true);
    setError("");
    try {
      const response = await listMemoryPosts(memory.id, cursor);
      setPosts((current) => [...current, ...response.posts]);
      setCursor(response.next_cursor);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "関連する投稿を読み込めませんでした。");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className={styles.postRelations}>
      {posts.length || cursor ? (
        <details>
          <summary>関連投稿: {posts.length}件{cursor ? "以上" : ""}</summary>
          <ul>
            {posts.map((post) => (
              <li key={post.post_id}>
                <Link href={`/posts/${post.post_id}`}>{formatDate(post.published_at)}の投稿</Link>
              </li>
            ))}
          </ul>
          {cursor ? (
            <button className={styles.loadMore} type="button" onClick={() => void loadMore()} disabled={isLoading}>
              {isLoading ? "読み込み中" : "投稿をさらに表示"}
            </button>
          ) : null}
          <p className={styles.relationStatus} role={error ? "alert" : "status"} aria-live="polite">
            {error || (isLoading ? "関連する投稿を読み込んでいます。" : "")}
          </p>
        </details>
      ) : <span>関連投稿: 0件</span>}
    </div>
  );
}

export function MemoryList({ response, params, selectedCampaign }: { response: MemoryListResponse; params: MemoryListParams; selectedCampaign: CampaignOption | null }) {
  const controller = useMemoryDeleteController();
  const selectedMemory = response.memories.find((memory) => memory.id === controller.state.selectedId);
  const visibleMemories = response.memories.filter((memory) => memory.id !== controller.state.deletedId);

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <h1>記憶</h1>
        <p>AIが参照する採用文脈の長期記憶</p>
      </header>

      <section className={styles.search} aria-labelledby="memory-search-title">
        <h2 id="memory-search-title" className={styles.visuallyHidden}>記憶を探す</h2>
        <CampaignFilter key={`${params.campaignId ?? ""}:${params.query}`} initialCampaign={selectedCampaign} query={params.query} />
      </section>

      <section aria-labelledby="memory-results-title">
        <div className={params.query || params.campaignId ? styles.resultHeading : styles.visuallyHidden}>
          <h2 id="memory-results-title">{params.query ? `「${params.query}」に近い記憶` : params.campaignId ? `${selectedCampaign?.title ?? `施策ID ${params.campaignId}`} の記憶` : "蓄積した記憶"}</h2>
          {params.query ? <p>記憶の内容をもとに関連度順で表示しています。</p> : null}
        </div>

        {visibleMemories.length === 0 ? (
          <div className={styles.empty}>
            <h3>{params.query || params.campaignId ? "条件に合う記憶がありません" : "まだ記憶がありません"}</h3>
            <p>{params.query || params.campaignId ? "検索語や施策を変更してください。" : "投稿の計測が完了すると、結果から得た知見が蓄積されます。"}</p>
            {params.query || params.campaignId ? <Link href="/memories">検索条件をクリア</Link> : null}
          </div>
        ) : (
          <div className={styles.list}>
            {visibleMemories.map((memory) => (
              <article className={styles.card} key={memory.id}>
                <p className={styles.memoryText}>{memory.content}</p>
                <button className={styles.deleteButton} type="button" aria-label={`記憶ID ${memory.id}を削除する`} onClick={() => controller.open(memory.id)}>削除</button>
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
            {params.cursor ? <Link href={memoryPageHref(params)}>先頭へ</Link> : null}
            {response.next_cursor ? <Link href={memoryPageHref(params, response.next_cursor)}>次の20件</Link> : null}
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
              <button type="button" onClick={controller.close} disabled={controller.state.isPending} autoFocus>キャンセル</button>
              <button type="button" onClick={() => void controller.confirmDelete()} disabled={controller.state.isPending}>{controller.state.isPending ? "削除中" : "削除する"}</button>
            </div>
          </section>
        </div>
      ) : null}
      <p className={styles.liveMessage} aria-live="polite">{controller.state.deletedId ? "記憶を削除しました。" : ""}</p>
    </main>
  );
}
