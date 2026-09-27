import type { FormEvent, RefObject } from "react";

import { Brand } from "@/shared/components/Brand/Brand";

import styles from "./LoginView.module.scss";

type LoginViewProps = {
  email: string;
  password: string;
  emailError: string | null;
  passwordError: string | null;
  formError: string | null;
  isPasswordVisible: boolean;
  isPending: boolean;
  shouldReload: boolean;
  emailRef: RefObject<HTMLInputElement | null>;
  passwordRef: RefObject<HTMLInputElement | null>;
  formErrorRef: RefObject<HTMLDivElement | null>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onEmailChange: (email: string) => void;
  onPasswordChange: (password: string) => void;
  onPasswordVisibilityToggle: () => void;
  onReload: () => void;
};

export function LoginView({
  email,
  password,
  emailError,
  passwordError,
  formError,
  isPasswordVisible,
  isPending,
  shouldReload,
  emailRef,
  passwordRef,
  formErrorRef,
  onSubmit,
  onEmailChange,
  onPasswordChange,
  onPasswordVisibilityToggle,
  onReload,
}: LoginViewProps) {
  const emailDescription = emailError ? "email-error" : undefined;
  const passwordDescription = passwordError ? "password-error" : undefined;

  return (
    <div className={styles.page}>
      <a className="skipLink" href="#main-content">本文へ移動する</a>
      <section className={styles.brandPanel} aria-label="Hiromeru">
        <Brand inverse />
        <p>SNS採用を自動化する<br />AIエージェント</p>
      </section>

      <main className={styles.main} id="main-content" tabIndex={-1}>
        <div className={styles.mobileBrand}>
          <Brand />
          <p>SNS採用を自動化するAIエージェント</p>
        </div>

        <div className={styles.card}>
          <div className={styles.cardBrand}><Brand /></div>
          <h1>ログイン</h1>
          <form noValidate onSubmit={onSubmit}>
            <div className={styles.field}>
              <label htmlFor="email">メールアドレス</label>
              <input
                ref={emailRef}
                id="email"
                name="email"
                type="email"
                inputMode="email"
                autoComplete="username"
                value={email}
                aria-invalid={emailError !== null}
                aria-describedby={emailDescription}
                disabled={isPending}
                onChange={(event) => onEmailChange(event.currentTarget.value)}
              />
              {emailError ? <p id="email-error" className={styles.fieldError}>{emailError}</p> : null}
            </div>

            <div className={styles.field}>
              <div className={styles.passwordLabel}>
                <label htmlFor="password">パスワード</label>
                <button type="button" onClick={onPasswordVisibilityToggle} disabled={isPending}>
                  {isPasswordVisible ? "隠す" : "表示"}
                </button>
              </div>
              <input
                ref={passwordRef}
                id="password"
                name="password"
                type={isPasswordVisible ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                aria-invalid={passwordError !== null}
                aria-describedby={passwordDescription}
                disabled={isPending}
                onChange={(event) => onPasswordChange(event.currentTarget.value)}
              />
              {passwordError ? <p id="password-error" className={styles.fieldError}>{passwordError}</p> : null}
            </div>

            <button className={styles.submit} type="submit" disabled={isPending}>
              {isPending ? "ログイン中…" : "ログイン"}
            </button>

            <div aria-live="polite" className={styles.status}>
              {emailError && passwordError && emailError === passwordError
                ? emailError
                : isPending ? "ログインしています" : null}
            </div>

            {formError ? (
              <div ref={formErrorRef} className={styles.formError} role="alert" tabIndex={-1}>
                <p>{formError}</p>
                {shouldReload ? <button type="button" onClick={onReload}>ページを再読み込み</button> : null}
              </div>
            ) : null}
          </form>

          <footer className={styles.cardFooter}>
            <span>サービス利用相談はXまで</span>
            <a href="https://x.com/hiromaru_jp" target="_blank" rel="noreferrer">
              @hiromaru_jp<span className={styles.visuallyHidden}>（新しいタブで開く）</span>
            </a>
          </footer>
        </div>
      </main>
    </div>
  );
}
