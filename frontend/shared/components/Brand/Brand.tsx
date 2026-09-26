import styles from "./Brand.module.scss";

type BrandProps = {
  inverse?: boolean;
};

export function Brand({ inverse = false }: BrandProps) {
  return (
    <span className={inverse ? `${styles.root} ${styles.inverse}` : styles.root}>
      <span aria-hidden="true" className={styles.mark}>H</span>
      <span translate="no">HIROMERU</span>
    </span>
  );
}
