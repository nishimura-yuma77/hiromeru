import type { CSSProperties, ReactNode } from "react";

type RouteStateProps = {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
  live?: "polite" | "assertive";
};

const styles = {
  main: {
    alignItems: "center",
    display: "flex",
    justifyContent: "center",
    minHeight: "100%",
    padding: "var(--space-page, 1.5rem)",
  },
  panel: {
    background: "var(--color-surface, #fff)",
    border: "1px solid var(--color-border, rgb(20 33 27 / 14%))",
    borderRadius: "var(--radius-lg, 1.75rem)",
    boxShadow: "var(--shadow-panel, 0 1.75rem 5rem rgb(13 77 56 / 12%))",
    maxWidth: "36rem",
    padding: "clamp(2rem, 8vw, 4rem)",
    width: "100%",
  },
  eyebrow: {
    color: "var(--color-brand-primary, #0e5a42)",
    fontSize: "var(--font-size-sm, 0.875rem)",
    fontWeight: 650,
    letterSpacing: "0.08em",
    margin: "0 0 0.75rem",
  },
  title: {
    fontSize: "clamp(1.75rem, 7vw, 2.6rem)",
    letterSpacing: "-0.035em",
    lineHeight: 1.2,
    margin: 0,
  },
  description: {
    color: "var(--color-text-secondary, #66756d)",
    lineHeight: 1.85,
    margin: "1rem 0 0",
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    gap: "0.75rem",
    marginTop: "2rem",
  },
} satisfies Record<string, CSSProperties>;

export const routeStateActionStyle: CSSProperties = {
  alignItems: "center",
  background: "var(--color-brand-primary, #0e5a42)",
  border: 0,
  borderRadius: "var(--radius-pill, 999px)",
  color: "var(--color-text-on-brand, #fff)",
  cursor: "pointer",
  display: "inline-flex",
  fontWeight: 650,
  justifyContent: "center",
  minHeight: "2.75rem",
  padding: "0.75rem 1.25rem",
  textDecoration: "none",
};

export const routeStateSecondaryActionStyle: CSSProperties = {
  ...routeStateActionStyle,
  background: "transparent",
  border: "1px solid var(--color-border-strong, rgb(20 33 27 / 28%))",
  color: "var(--color-text-primary, #10231a)",
};

export function RouteState({ eyebrow, title, description, actions, live }: RouteStateProps) {
  return (
    <main id="main-content" style={styles.main}>
      <section
        aria-live={live}
        aria-busy={live === "polite" ? true : undefined}
        role={live === "assertive" ? "alert" : live === "polite" ? "status" : undefined}
        style={styles.panel}
      >
        <p style={styles.eyebrow}>{eyebrow}</p>
        <h1 style={styles.title}>{title}</h1>
        <p style={styles.description}>{description}</p>
        {actions ? <div style={styles.actions}>{actions}</div> : null}
      </section>
    </main>
  );
}
