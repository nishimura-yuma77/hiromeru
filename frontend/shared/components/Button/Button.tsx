import type { ComponentPropsWithRef, ReactNode } from "react";

import { Spinner } from "@/shared/components/Spinner/Spinner";

import styles from "./Button.module.scss";

type ButtonProps = Omit<ComponentPropsWithRef<"button">, "children" | "className" | "style"> & {
  children: ReactNode;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "small" | "medium";
  isLoading?: boolean;
  loadingLabel?: string;
  block?: boolean;
  iconOnly?: boolean;
};

export function Button({
  children,
  variant = "primary",
  size = "medium",
  isLoading = false,
  loadingLabel = "処理中",
  block = false,
  iconOnly = false,
  type = "button",
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || isLoading}
      aria-busy={isLoading ? true : undefined}
      className={`${styles.button} ${styles[variant]} ${styles[size]}${block ? ` ${styles.block}` : ""}${iconOnly ? ` ${styles.iconOnly}` : ""}`}
    >
      <span className={styles.labels}>
        <span aria-hidden={isLoading} className={isLoading ? styles.hidden : undefined}>{children}</span>
        <span aria-hidden={!isLoading} className={`${styles.loading}${isLoading ? "" : ` ${styles.hidden}`}`}>
          <Spinner size="small" />{loadingLabel}
        </span>
      </span>
    </button>
  );
}
