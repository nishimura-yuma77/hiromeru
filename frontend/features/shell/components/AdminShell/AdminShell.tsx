import Link from "next/link";
import type { ReactNode } from "react";

import { Brand } from "@/shared/components/Brand/Brand";
import { Button } from "@/shared/components/Button/Button";

import styles from "./AdminShell.module.scss";

type AdminShellProps = {
  email: string;
  logoutLoading: boolean;
  logoutError: string | null;
  onLogout: () => void;
  children: ReactNode;
};

// SC-10・SC-11の管理用レイアウト。管理ナビは「ユーザー管理」のみ（SCREEN_DESIGN 6.16）。
export function AdminShell({ email, logoutLoading, logoutError, onLogout, children }: AdminShellProps) {
  return (
    <div className={styles.shell}>
      <a className="skipLink" href="#main-content">本文へ移動する</a>
      <header className={styles.header}>
        <div className={styles.brand}>
          <Brand />
          <span className={styles.badge}>管理</span>
        </div>
        <nav aria-label="管理メニュー" className={styles.navigation}>
          <Link href="/admin/users" aria-current="page">ユーザー管理</Link>
        </nav>
        <div className={styles.account}>
          <p title={email}>{email}</p>
          <Link className={styles.marketingLink} href="/chat">チャット・施策へ</Link>
          <Button variant="ghost" size="small" isLoading={logoutLoading} loadingLabel="ログアウト中" onClick={onLogout}>ログアウト</Button>
        </div>
      </header>
      <main className={styles.main} id="main-content" tabIndex={-1}>{children}</main>
      {logoutError ? <div className={styles.logoutError} role="alert">{logoutError}</div> : null}
    </div>
  );
}
