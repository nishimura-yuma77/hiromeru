"use client";

import Link from "next/link";
import { Button } from "@/shared/components/Button/Button";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { sessionKeys } from "../queries/sessionKeys";
import { useSessionListInfiniteQuery } from "../queries/sessionQueries";
import type { AgentSession, SessionList } from "../types";
import styles from "../styles/Chat.module.scss";

const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Tokyo",
});

function SessionLink({ session, active }: { session: AgentSession; active: boolean }) {
  const title = session.title ?? "無題の会話";
  return (
    <li>
      <Link
        aria-current={active ? "page" : undefined}
        aria-label={`${title}、更新 ${dateFormatter.format(new Date(session.updated_at))}`}
        className={`${styles.sessionLink} ${active ? styles.sessionLinkActive : ""}`}
        href={`/chat/${session.session_id}`}
      >
        <span>{title}</span>
        <time dateTime={session.updated_at}>{dateFormatter.format(new Date(session.updated_at))}</time>
      </Link>
    </li>
  );
}

export function ChatWorkspace({ initialSessions, children }: { initialSessions: SessionList; children: React.ReactNode }) {
  const pathname = usePathname();
  const [isSessionListOpen, setIsSessionListOpen] = useState(true);
  const client = useQueryClient();
  const listQuery = useSessionListInfiniteQuery(initialSessions);
  const pages = listQuery.data?.pages ?? [initialSessions];
  const seen = new Set<number>();
  const sessions = pages.flatMap((page) => page.sessions.filter((session) => {
    if (seen.has(session.session_id)) return false;
    seen.add(session.session_id);
    return true;
  }));

  useEffect(() => {
    const mobileLayout = window.matchMedia("(max-width: 64rem)");
    const restoreMobileList = () => {
      if (mobileLayout.matches) setIsSessionListOpen(true);
    };
    mobileLayout.addEventListener("change", restoreMobileList);
    return () => mobileLayout.removeEventListener("change", restoreMobileList);
  }, []);

  useEffect(() => {
    function refresh() { void client.invalidateQueries({ queryKey: sessionKeys.list() }); }
    window.addEventListener("chat:sessions-changed", refresh);
    return () => window.removeEventListener("chat:sessions-changed", refresh);
  }, [client]);

  return (
    <div className={`${styles.workspace}${isSessionListOpen ? "" : ` ${styles.workspaceCollapsed}`}`}>
      <aside aria-label="会話一覧" className={styles.sidebar}>
        <div className={styles.listHeader}>
          <h1>会話一覧</h1>
          <div className={styles.listToggle}>
            <Button
              aria-controls="chat-session-list"
              aria-expanded={isSessionListOpen}
              aria-label={isSessionListOpen ? "会話一覧を閉じる" : "会話一覧を開く"}
              variant="secondary"
              iconOnly
              onClick={() => setIsSessionListOpen((open) => !open)}
              title={isSessionListOpen ? "会話一覧を閉じる" : "会話一覧を開く"}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="4" width="18" height="16" rx="2" />
                <path d="M9 4v16" />
                <path d={isSessionListOpen ? "m16 9-3 3 3 3" : "m14 9 3 3-3 3"} />
              </svg>
            </Button>
          </div>
        </div>
        <div className={styles.sidebarBody} id="chat-session-list" inert={isSessionListOpen ? undefined : true}>
          <Link className={styles.newButton} href="/chat/new">
            <span aria-hidden="true">＋</span> 新しい会話
          </Link>
          {sessions.length === 0 ? (
            <div className={styles.emptyList}>
              <p>まだ会話がありません。マーケティングの依頼から始めましょう。</p>
              <Link href="/chat/new">新しい会話を始める</Link>
            </div>
          ) : (
            <ul className={styles.sessionList}>
              {sessions.map((session) => (
                <SessionLink
                  active={pathname === `/chat/${session.session_id}`}
                  key={session.session_id}
                  session={session}
                />
              ))}
            </ul>
          )}
          <div className={styles.loadMore} aria-live="polite">
            {listQuery.error ? <p role="alert">会話を読み込めませんでした。</p> : null}
            {listQuery.hasNextPage ? (
              <Button variant="ghost" size="small" isLoading={listQuery.isFetchingNextPage} loadingLabel="会話を読み込み中" onClick={() => void listQuery.fetchNextPage()}>
                {listQuery.error ? "もう一度読み込む" : "さらに読み込む"}
              </Button>
            ) : null}
          </div>
        </div>
      </aside>
      <section aria-label="会話内容" className={styles.content} id="main-content" tabIndex={-1}>
        {children}
      </section>
    </div>
  );
}
