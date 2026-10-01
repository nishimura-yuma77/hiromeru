import type { ReactNode } from "react";

import styles from "./Disclosure.module.scss";

export function Disclosure({ summary, children, defaultOpen = false }: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className={styles.disclosure} open={defaultOpen ? true : undefined}>
      <summary>{summary}</summary>
      <div className={styles.content}>{children}</div>
    </details>
  );
}
