import styles from "./Spinner.module.scss";

export function Spinner({ size = "medium" }: { size?: "small" | "medium" | "large" }) {
  return <span aria-hidden="true" className={`${styles.spinner} ${styles[size]}`} />;
}
