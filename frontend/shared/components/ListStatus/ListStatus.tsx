import { Button } from "@/shared/components/Button/Button";
import { Spinner } from "@/shared/components/Spinner/Spinner";

import styles from "./ListStatus.module.scss";

export function ListStatus({ loading, error, onRetry, loadingLabel = "読み込んでいます" }: {
  loading: boolean;
  error: string;
  onRetry: () => void;
  loadingLabel?: string;
}) {
  return (
    <>
      {loading ? <div className={styles.loading} role="status"><Spinner size="large" />{loadingLabel}</div> : null}
      {error ? <div className={styles.error} role="alert">{error} <Button variant="secondary" size="small" onClick={onRetry}>もう一度読み込む</Button></div> : null}
    </>
  );
}
