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
import { memoryPageHref, type MemoryListParams } from "@/features/memories/utils/memoryParams";

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
    <section aria-label="関連する施策">
      <h3>関連する施策</h3>
      {campaigns.length ? (
        <ul>
          {campaigns.map((campaign) => (
            <li key={campaign.id}>
              <Link href={`/campaigns/${campaign.id}`}>{campaign.title}</Link>
              {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
            </li>
          ))}
        </ul>
      ) : <p>関連する施策はありません。</p>}
      {cursor ? (
        <button className={styles.loadMore} type="button" onClick={() => void loadMore()} disabled={isLoading}>
          {isLoading ? "読み込み中" : "施策をさらに表示"}
        </button>
      ) : null}
      <p className={styles.relationStatus} role={error ? "alert" : "status"} aria-live="polite">
        {error || (isLoading ? "関連する施策を読み込んでいます。" : "")}
      </p>
    </section>
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
    <section aria-label="関連する投稿">
      <h3>関連する投稿</h3>
      {posts.length ? (
        <ul>
          {posts.map((post) => (
            <li key={post.post_id}>
              <Link href={`/posts/${post.post_id}`}>{formatDate(post.published_at)}の投稿</Link>
            </li>
          ))}
        </ul>
      ) : <p>関連する投稿はありません。</p>}
      {cursor ? (
        <button className={styles.loadMore} type="button" onClick={() => void loadMore()} disabled={isLoading}>
          {isLoading ? "読み込み中" : "投稿をさらに表示"}
        </button>
      ) : null}
      <p className={styles.relationStatus} role={error ? "alert" : "status"} aria-live="polite">
        {error || (isLoading ? "関連する投稿を読み込んでいます。" : "")}
      </p>
    </section>
  );
}

export function MemoryList({ response, params }: { response: MemoryListResponse; params: MemoryListParams }) {
  const controller = useMemoryDeleteController();
  const selectedMemory = response.memories.find((memory) => memory.id === controller.state.selectedId);
  const visibleMemories = response.memories.filter((memory) => memory.id !== controller.state.deletedId);

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Long-term memory</p>
        <h1>記憶</h1>
        <p>投稿の結果から得た知見と、その根拠になった施策・投稿を確認できます。</p>
      </header>

      <section className={styles.search} aria-labelledby="memory-search-title">
        <h2 id="memory-search-title">記憶を検索</h2>
        <form action="/memories" method="get">
          <label>
            <span>検索語</span>
            <input type="search" name="query" defaultValue={params.query} maxLength={1000} placeholder="蓄積した知見を自然な言葉で検索" />
          </label>
          <label className={styles.campaignField}>
            <span>施策ID</span>
            <input type="text" name="campaign_id" inputMode="numeric" pattern="[1-9][0-9]*" defaultValue={params.campaignId ?? ""} />
          </label>
          <button type="submit">検索</button>
          <Link href="/memories">検索をクリア</Link>
        </form>
      </section>

      <section aria-labelledby="memory-results-title">
        <div className={styles.resultHeading}>
          <div><p className={styles.eyebrow}>Knowledge base</p><h2 id="memory-results-title">{params.query ? `「${params.query}」に近い記憶` : params.campaignId ? `施策ID ${params.campaignId} の記憶` : "蓄積した記憶"}</h2></div>
          <p>{params.query ? "記憶の内容をもとに関連度順で表示しています。" : "新しい記憶から表示"}</p>
        </div>

        {visibleMemories.length === 0 ? (
          <div className={styles.empty}>
            <h3>{params.query || params.campaignId ? "条件に合う記憶がありません" : "まだ記憶がありません"}</h3>
            <p>{params.query || params.campaignId ? "検索語や施策IDを変更してください。" : "投稿の計測が完了すると、結果から得た知見が蓄積されます。"}</p>
            {params.query || params.campaignId ? <Link href="/memories">検索条件をクリア</Link> : null}
          </div>
        ) : (
          <div className={styles.list}>
            {visibleMemories.map((memory) => (
              <article className={styles.card} key={memory.id}>
                <div className={styles.memoryText}>
                  <p className={styles.recordId}>Memory {memory.id}</p>
                  <p>{memory.content}</p>
                </div>
                <div className={styles.related}>
                  <RelatedCampaigns memory={memory} />
                  <RelatedPosts memory={memory} />
                </div>
                <button className={styles.deleteButton} type="button" onClick={() => controller.open(memory.id)}>この記憶を削除</button>
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
