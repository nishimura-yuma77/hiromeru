import { LoginBrandPanel } from "./LoginBrandPanel";
import { LoginFormCard, type LoginFormCardProps } from "./LoginFormCard";
import styles from "./LoginView.module.scss";

export function LoginView(props: LoginFormCardProps) {
  return (
    <div className={styles.page}>
      <a className="skipLink" href="#main-content">本文へ移動する</a>
      <LoginBrandPanel />
      <main className={styles.main} id="main-content" tabIndex={-1}>
        <LoginFormCard {...props} />
      </main>
    </div>
  );
}
