import Link from "next/link";

import styles from "../styles/Chat.module.scss";

export function ChatIndex() {
  return (
    <div className={styles.indexPrompt}>
      <span aria-hidden="true" className={styles.indexMark}>H</span>
      <h2>会話を選択してください</h2>
      <p>過去の相談を続けるか、新しい会話を始められます。</p>
      <Link href="/chat/new">新しい会話を始める</Link>
    </div>
  );
}
