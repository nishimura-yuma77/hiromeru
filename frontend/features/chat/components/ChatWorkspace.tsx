"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useReducer, useRef } from "react";

import { listSessions } from "../api";
import type { AgentSession, SessionList } from "../types";
import styles from "../styles/Chat.module.scss";

type ListState = SessionList & { loading: boolean; error: string | null };
type ListAction =
  | { type: "loading" }
  | { type: "loaded"; page: SessionList }
  | { type: "refreshed"; page: SessionList }
  | { type: "failed" };

function listReducer(state: ListState, action: ListAction): ListState {
  if (action.type === "loading") return { ...state, loading: true, error: null };
  if (action.type === "failed") return { ...state, loading: false, error: "会話を読み込めませんでした。" };
  if (action.type === "refreshed") return { ...action.page, loading: false, error: null };
  const seen = new Set(state.sessions.map((session) => session.session_id));
  return {
    sessions: [...state.sessions, ...action.page.sessions.filter((session) => !seen.has(session.session_id))],
    next_cursor: action.page.next_cursor,
    loading: false,
    error: null,
  };
}

const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
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
  const [state, dispatch] = useReducer(listReducer, {
    ...initialSessions,
    loading: false,
    error: null,
  });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    async function refresh() {
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        dispatch({ type: "refreshed", page: await listSessions(null, controller.signal) });
      } catch {
        // A background refresh must not replace the usable list with an error.
      }
    }
    window.addEventListener("chat:sessions-changed", refresh);
    return () => {
      window.removeEventListener("chat:sessions-changed", refresh);
      abortRef.current?.abort();
    };
  }, []);

  async function loadMore() {
    if (!state.next_cursor || state.loading) return;
    dispatch({ type: "loading" });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      dispatch({ type: "loaded", page: await listSessions(state.next_cursor, controller.signal) });
    } catch {
      if (!controller.signal.aborted) dispatch({ type: "failed" });
    }
  }

  return (
    <div className={styles.workspace}>
      <aside aria-label="会話一覧" className={styles.sidebar}>
        <div className={styles.listHeader}>
          <h1>会話</h1>
          <Link className={styles.newButton} href="/chat/new">
            <span aria-hidden="true">＋</span> 新しい会話
          </Link>
        </div>
        {state.sessions.length === 0 ? (
          <div className={styles.emptyList}>
            <p>まだ会話がありません。マーケティングの依頼から始めましょう。</p>
            <Link href="/chat/new">新しい会話を始める</Link>
          </div>
        ) : (
          <ul className={styles.sessionList}>
            {state.sessions.map((session) => (
              <SessionLink
                active={pathname === `/chat/${session.session_id}`}
                key={session.session_id}
                session={session}
              />
            ))}
          </ul>
        )}
        <div className={styles.loadMore} aria-live="polite">
          {state.error ? <p role="alert">{state.error}</p> : null}
          {state.next_cursor ? (
            <button disabled={state.loading} onClick={loadMore} type="button">
              {state.loading ? "読み込み中" : state.error ? "もう一度読み込む" : "さらに読み込む"}
            </button>
          ) : null}
        </div>
      </aside>
      <section aria-label="会話内容" className={styles.content} id="main-content" tabIndex={-1}>
        {children}
      </section>
    </div>
  );
}
