import Link from "next/link";
import type { ReactNode, RefObject } from "react";

import { Brand } from "@/shared/components/Brand/Brand";
import type { AppNavigationId, AppNavigationItem } from "@/features/shell/types/navigation";

import styles from "./AppShell.module.scss";

type AppShellProps = {
  email: string;
  navigationItems: AppNavigationItem[];
  activeNavigationId: AppNavigationId;
  drawerOpen: boolean;
  logoutLoading: boolean;
  logoutError: string | null;
  children: ReactNode;
  menuButtonRef: RefObject<HTMLButtonElement | null>;
  drawerRef: RefObject<HTMLDivElement | null>;
  drawerCloseButtonRef: RefObject<HTMLButtonElement | null>;
  onDrawerOpen: () => void;
  onDrawerClose: () => void;
  onLogout: () => void;
};

function NavigationIcon({ id }: { id: AppNavigationId }) {
  const paths: Record<AppNavigationId, ReactNode> = {
    chat: <path d="M4 5h16v11H8l-4 3V5Z" />,
    campaigns: <path d="M4 6h16v13H4V6Zm4 0V4h8v2" />,
    posts: <path d="M5 4h14v16H5V4Zm3 4h8M8 12h8M8 16h5" />,
    metrics: <path d="M5 19V9m7 10V5m7 14v-7" />,
    memories: <path d="M8 5a4 4 0 0 1 8 0v1a4 4 0 0 1 2 7.5A4 4 0 0 1 14 19h-4a4 4 0 0 1-4-5.5A4 4 0 0 1 8 6V5Z" />,
  };
  return <svg aria-hidden="true" viewBox="0 0 24 24">{paths[id]}</svg>;
}

function Navigation({
  items,
  activeId,
  onNavigate,
}: {
  items: AppNavigationItem[];
  activeId: AppNavigationId;
  onNavigate?: () => void;
}) {
  return (
    <nav aria-label="メインメニュー" className={styles.navigation}>
      <ul>
        {items.map((navigationItem) => (
          <li key={navigationItem.id}>
            <Link
              href={navigationItem.href}
              aria-current={navigationItem.id === activeId ? "page" : undefined}
              onClick={onNavigate}
            >
              <NavigationIcon id={navigationItem.id} />
              <span>{navigationItem.label}</span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

function Account({ email, isPending, onLogout }: { email: string; isPending: boolean; onLogout: () => void }) {
  return (
    <div className={styles.account}>
      <p title={email}>{email}</p>
      <button type="button" disabled={isPending} onClick={onLogout}>
        {isPending ? "ログアウト中…" : "ログアウト"}
      </button>
    </div>
  );
}

export function AppShell({
  email,
  navigationItems,
  activeNavigationId,
  drawerOpen,
  logoutLoading,
  logoutError,
  children,
  menuButtonRef,
  drawerRef,
  drawerCloseButtonRef,
  onDrawerOpen,
  onDrawerClose,
  onLogout,
}: AppShellProps) {
  return (
    <div className={styles.shell}>
      <a className="skipLink" href="#main-content">本文へ移動する</a>

      <aside className={styles.sidebar}>
        <Brand inverse />
        <Navigation items={navigationItems} activeId={activeNavigationId} />
        <Account email={email} isPending={logoutLoading} onLogout={onLogout} />
      </aside>

      <div className={styles.app} inert={drawerOpen ? true : undefined}>
        <header className={styles.mobileHeader}>
          <button
            ref={menuButtonRef}
            type="button"
            aria-controls="app-navigation-drawer"
            aria-expanded={drawerOpen}
            aria-label="メニューを開く"
            onClick={onDrawerOpen}
          >
            <span aria-hidden="true" />
            <span aria-hidden="true" />
            <span aria-hidden="true" />
          </button>
          <Brand />
        </header>
        <div className={styles.main}>{children}</div>
      </div>

      {drawerOpen ? (
        <div className={styles.drawerLayer}>
          <button className={styles.backdrop} type="button" aria-label="メニューを閉じる" onClick={onDrawerClose} />
          <div
            ref={drawerRef}
            className={styles.drawer}
            id="app-navigation-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="メインメニュー"
          >
            <div className={styles.drawerHeader}>
              <strong>メニュー</strong>
              <button ref={drawerCloseButtonRef} type="button" aria-label="メニューを閉じる" onClick={onDrawerClose}>×</button>
            </div>
            <Navigation items={navigationItems} activeId={activeNavigationId} onNavigate={onDrawerClose} />
            <Account email={email} isPending={logoutLoading} onLogout={onLogout} />
          </div>
        </div>
      ) : null}

      {logoutError ? <div className={styles.logoutError} role="alert">{logoutError}</div> : null}
    </div>
  );
}
