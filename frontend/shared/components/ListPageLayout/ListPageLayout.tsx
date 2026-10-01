import Link from "next/link";
import type { ReactNode } from "react";

import styles from "./ListPageLayout.module.scss";

export function ListPageLayout({ title, description, actions, filters, children }: {
  title: string;
  description?: string;
  actions?: ReactNode;
  filters: ReactNode;
  children: ReactNode;
}) {
  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <h1>{title}</h1>
          {description ? <p>{description}</p> : null}
        </div>
        {actions ? <div className={styles.actions}>{actions}</div> : null}
      </header>
      <div className={styles.filters}>{filters}</div>
      <div className={styles.content}>{children}</div>
    </main>
  );
}

export function ListPageAction({ href, children }: { href: string; children: ReactNode }) {
  return <Link className={styles.action} href={href}>{children}</Link>;
}
