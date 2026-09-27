import { Brand } from "@/shared/components/Brand/Brand";

import styles from "./LoginView.module.scss";

const benefits = [
  "施策を立案してX投稿案を自動生成",
  "投稿後の成果を計測",
  "採用文脈をAIが長期記憶",
];

export function LoginBrandPanel() {
  return (
    <section className={styles.brandPanel} aria-label="Hiromeruの紹介">
      <Brand inverse variant="login" />
      <div className={styles.brandIntro}>
        <p className={styles.heroTitle}>SNS採用を<br />自動化する<br />AIエージェント</p>
        <p className={styles.brandDescription}>
          AIとの対話を通じて採用施策の立案から<br className={styles.desktopBreak} />
          X投稿の公開・成果計測まで一気通貫で管理。
        </p>
      </div>
      <ul className={styles.benefits}>
        {benefits.map((benefit) => (
          <li key={benefit}>
            <span aria-hidden="true" className={styles.check}>✓</span>
            <span>{benefit}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
