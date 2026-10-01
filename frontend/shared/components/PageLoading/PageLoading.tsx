import { Spinner } from "@/shared/components/Spinner/Spinner";

import styles from "./PageLoading.module.scss";

export function PageLoading({ withinShell = false }: { withinShell?: boolean }) {
  return (
    <div className={`${styles.loading}${withinShell ? ` ${styles.withinShell}` : ""}`} role="status" aria-live="polite">
      <Spinner size="large" />
      <span>読み込み中です</span>
    </div>
  );
}
