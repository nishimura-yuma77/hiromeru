import type { ComponentPropsWithRef, ReactNode } from "react";

import styles from "./Input.module.scss";

type InputProps = Omit<ComponentPropsWithRef<"input">, "children" | "className" | "style" | "type"> & {
  type?: "text" | "search" | "email" | "password" | "url" | "date" | "number";
  leadingIcon?: ReactNode;
  trailingAction?: ReactNode;
};

export function Input({ leadingIcon, trailingAction, type = "text", ...props }: InputProps) {
  return (
    <span className={styles.control}>
      {leadingIcon ? <span className={styles.icon} aria-hidden="true">{leadingIcon}</span> : null}
      <input {...props} type={type} />
      {trailingAction ? <span className={styles.action}>{trailingAction}</span> : null}
    </span>
  );
}
