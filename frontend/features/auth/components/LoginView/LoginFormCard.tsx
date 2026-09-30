import type { FormEvent, RefObject } from "react";
import { Input } from "@/shared/components/Input/Input";

import styles from "./LoginView.module.scss";

export type LoginFormCardProps = {
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

export function LoginFormCard({
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
}: LoginFormCardProps) {
  return (
    <div className={styles.formColumn}>
      <div className={styles.card}>
        <h1>ログイン</h1>
        <p className={styles.cardIntro}>アカウント情報を入力してください</p>
        <form noValidate onSubmit={onSubmit}>
          <div className={styles.field}>
            <label htmlFor="email">メールアドレス</label>
            <Input
              ref={emailRef}
              id="email"
              name="email"
              type="email"
              inputMode="email"
              autoComplete="username"
              placeholder="user@example.com"
              value={email}
              aria-invalid={emailError !== null}
              aria-describedby={emailError ? "email-error" : undefined}
              disabled={isPending}
              onChange={(event) => onEmailChange(event.currentTarget.value)}
            />
            {emailError ? <p id="email-error" className={styles.fieldError}>{emailError}</p> : null}
          </div>

          <div className={styles.field}>
            <label htmlFor="password">パスワード</label>
            <div className={styles.passwordControl}>
              <Input
                ref={passwordRef}
                id="password"
                name="password"
                type={isPasswordVisible ? "text" : "password"}
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                aria-invalid={passwordError !== null}
                aria-describedby={passwordError ? "password-error" : undefined}
                disabled={isPending}
                onChange={(event) => onPasswordChange(event.currentTarget.value)}
                trailingAction={<button type="button" onClick={onPasswordVisibilityToggle} disabled={isPending}>
                  {isPasswordVisible ? "隠す" : "表示"}
                </button>}
              />
            </div>
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
      </div>
      <p className={styles.helpText}>パスワードを忘れた場合は管理者にお問い合わせください</p>
    </div>
  );
}
