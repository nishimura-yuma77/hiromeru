import styles from "./LandingPage.module.scss";

const X_PROFILE_URL = "https://x.com/hiromaru_jp";

const benefits = [
  {
    title: "探す時間を減らす",
    description: "過去の施策、投稿、結果をAIが探し、今回の企画に必要な材料だけを集めます。",
  },
  {
    title: "判断を次へ残す",
    description: "何を試し、どう反応されたかを施策に紐づけ、次回の判断材料として残します。",
  },
  {
    title: "公開は人が決める",
    description: "AIが施策や投稿を作っても、承認操作があるまでXへの公開は実行しません。",
  },
];

const processSteps = [
  {
    title: "前回を参照する",
    description: "依頼に近い施策と、公開後の結果をAIが見つけます。",
    output: "過去の施策・投稿結果",
  },
  {
    title: "今回を組み立てる",
    description: "過去の知見と採用背景から、施策と投稿案をまとめます。",
    output: "施策案・投稿案",
  },
  {
    title: "結果を記憶する",
    description: "公開後の初週データを計測し、次の施策で使える知見にします。",
    output: "次回の判断材料",
  },
];

function XLogo() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24">
      <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24h-6.657l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231 5.45-6.231Zm-1.161 17.52h1.833L7.084 4.126H5.117L17.083 19.77Z" />
    </svg>
  );
}

function XConsultationLink({ className }: { className: string }) {
  return (
    <a
      className={className}
      href={X_PROFILE_URL}
      rel="noreferrer"
      target="_blank"
    >
      Xで相談する
      <XLogo />
      <span className={styles.visuallyHidden}>（新しいタブで開く）</span>
    </a>
  );
}

export function LandingPage() {
  return (
    <div className={styles.page}>
      <a className="skipLink" href="#main-content">
        本文へ移動する
      </a>

      <header className={styles.header}>
        <a className={styles.brand} href="#top" aria-label="Hiromeru トップへ">
          <span aria-hidden="true" className={styles.brandMark}>
            H
          </span>
          <span translate="no">HIROMERU</span>
        </a>

        <nav aria-label="メインナビゲーション" className={styles.navigation}>
          <a href="#value">できること</a>
          <a href="#how-it-works">仕組み</a>
        </nav>

        <a className={styles.headerCta} href="/login">
          ログイン
        </a>
      </header>

      <main id="main-content" tabIndex={-1}>
        <section aria-labelledby="hero-title" className={styles.hero} id="top">
          <div className={styles.heroCopy}>
            <p className={styles.intro}>採用Xの運用を、毎回ゼロから始めない。</p>
            <h1 id="hero-title">前回の結果から、次の採用施策を考える。</h1>
            <p className={styles.heroDescription}>
              Hiromeruは、採用Xの企画、投稿、承認、計測を一つの記録につなぐAIエージェントです。
            </p>
            <div className={styles.heroActions}>
              <XConsultationLink className={styles.primaryCta} />
              <a className={styles.secondaryLink} href="#how-it-works">
                仕組みを見る
              </a>
            </div>
            <p className={styles.destinationNote}>公式X @hiromaru_jpを開きます</p>
          </div>

          <figure aria-labelledby="demo-caption" className={styles.demo}>
            <figcaption className={styles.demoHeader} id="demo-caption">
              <span>Campaign 024</span>
              <span className={styles.pendingStatus}>承認待ち</span>
            </figcaption>

            <div className={styles.demoBody}>
              <div className={`${styles.demoBlock} ${styles.sourceBlock}`}>
                <div className={styles.demoLabel}>
                  <span>参照した施策</span>
                  <span>Campaign 023</span>
                </div>
                <strong>働き方を伝える採用投稿</strong>
                <p>初週PV・応募ページ流入を取得済み</p>
              </div>

              <div className={`${styles.demoBlock} ${styles.insightBlock}`}>
                <span className={styles.insightMark} aria-hidden="true" />
                <div>
                  <span>前回から得た知見</span>
                  <p>制度名より、働く一日が見える投稿に反応が集まった。</p>
                </div>
              </div>

              <div className={`${styles.demoBlock} ${styles.proposalBlock}`}>
                <div className={styles.demoLabel}>
                  <span>今回の施策案</span>
                  <span>AIが作成</span>
                </div>
                <strong>開発者の一日から、働き方を具体的に伝える</strong>
                <dl>
                  <div>
                    <dt>対象</dt>
                    <dd>転職を検討中のWebエンジニア</dd>
                  </div>
                  <div>
                    <dt>次の操作</dt>
                    <dd>内容を確認して承認</dd>
                  </div>
                </dl>
              </div>
            </div>

            <div className={styles.demoFooter}>
              <span aria-hidden="true" className={styles.lockMark} />
              <p>Xへの公開は、承認されるまで実行しません</p>
              <span>人が確認</span>
            </div>
          </figure>
        </section>

        <section aria-labelledby="value-title" className={styles.valueSection} id="value">
          <div className={styles.sectionIntro}>
            <h2 id="value-title">投稿ではなく、運用を前に進める。</h2>
            <p>必要な機能を、採用Xを続けるための三つの価値に絞りました。</p>
          </div>

          <div className={styles.benefitGrid}>
            {benefits.map((benefit) => (
              <article key={benefit.title}>
                <span aria-hidden="true" className={styles.benefitMark} />
                <h3>{benefit.title}</h3>
                <p>{benefit.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          aria-labelledby="process-title"
          className={styles.processSection}
          id="how-it-works"
        >
          <div className={styles.processHeading}>
            <h2 id="process-title">一つの施策が、次の施策につながる。</h2>
            <p>
              企画から振り返りまでを分断せず、同じ施策記録の中で循環させます。
            </p>
          </div>

          <ol className={styles.processList}>
            {processSteps.map((step, index) => (
              <li key={step.title}>
                <span className={styles.stepNumber}>{index + 1}</span>
                <div className={styles.stepCopy}>
                  <h3>{step.title}</h3>
                  <p>{step.description}</p>
                </div>
                <span className={styles.stepOutput}>{step.output}</span>
              </li>
            ))}
          </ol>

          <div className={styles.approvalNote}>
            <div>
              <span className={styles.approvalDot} aria-hidden="true" />
              <p>AIの担当</p>
              <strong>調査、施策案、投稿案、計測</strong>
            </div>
            <div className={styles.approvalBoundary}>
              <span>承認</span>
            </div>
            <div>
              <span className={styles.approvalDot} aria-hidden="true" />
              <p>人の担当</p>
              <strong>修正、施策の確定、Xへの公開</strong>
            </div>
          </div>
        </section>

        <section aria-labelledby="contact-title" className={styles.contactSection}>
          <div>
            <h2 id="contact-title">今の採用X運用を、次に活かせる形へ。</h2>
            <p>Hiromeruの使い方や、現在の運用課題についてXで相談できます。</p>
          </div>
          <XConsultationLink className={styles.contactCta} />
        </section>
      </main>

      <footer className={styles.footer}>
        <a className={styles.brand} href="#top" aria-label="Hiromeru トップへ">
          <span aria-hidden="true" className={styles.brandMark}>
            H
          </span>
          <span translate="no">HIROMERU</span>
        </a>
        <a href={X_PROFILE_URL} rel="noreferrer" target="_blank">
          X / @hiromaru_jp
          <span className={styles.visuallyHidden}>（新しいタブで開く）</span>
        </a>
        <p>© 2026 Hiromeru</p>
      </footer>
    </div>
  );
}
