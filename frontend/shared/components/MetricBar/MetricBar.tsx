import type { CSSProperties } from "react";

import styles from "./MetricBar.module.scss";

type MetricBarStyle = CSSProperties & { "--metric-bar-size": string };

export function MetricBar({ value, max }: { value: number; max: number }) {
  const size = max > 0 ? Math.min(100, Math.max(0, (value / max) * 100)) : 0;

  return (
    <div className={styles.track} aria-hidden="true">
      <span className={styles.value} style={{ "--metric-bar-size": `${size}%` } as MetricBarStyle} />
    </div>
  );
}
