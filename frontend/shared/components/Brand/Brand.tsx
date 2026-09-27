import styles from "./Brand.module.scss";

type BrandProps = {
  inverse?: boolean;
  variant?: "default" | "login";
};

export function Brand({ inverse = false, variant = "default" }: BrandProps) {
  return (
    <span className={`${styles.root}${inverse ? ` ${styles.inverse}` : ""}${variant === "login" ? ` ${styles.login}` : ""}`}>
      <span aria-hidden="true" className={styles.mark}>H</span>
      <span translate="no">{variant === "login" ? "Hiromeru" : "HIROMERU"}</span>
    </span>
  );
}
