import type { FormEvent, RefObject } from "react";

import type { InvitationAcceptState } from "@/features/invitations/state/invitationAcceptReducer";
import { PASSWORD_RULE } from "@/features/invitations/state/invitationAcceptReducer";
import { Brand } from "@/shared/components/Brand/Brand";
import { Button } from "@/shared/components/Button/Button";
import { Input } from "@/shared/components/Input/Input";

import styles from "./InvitationAcceptView.module.scss";

type InvitationAcceptViewProps = InvitationAcceptState & {
  passwordRef: RefObject<HTMLInputElement | null>;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onPasswordChange: (password: string) => void;
  onPasswordVisibilityToggle: () => void;
};

export function InvitationAcceptView({
  password,
  isPasswordVisible,
  isPending,
  passwordError,
  formError,
  isLinkInvalid,
  passwordRef,
  onSubmit,
  onPasswordChange,
  onPasswordVisibilityToggle,
}: InvitationAcceptViewProps) {
  return (
    <div className={styles.page}>
      <main className={styles.card} id="main-content">
        <Brand />
        <h1>パスワードの設定</h1>
        {isLinkInvalid ? (
          <div className={styles.invalid} role="alert">
            <p>この招待リンクは利用できません。管理者に再送を依頼してください</p>
          </div>
        ) : (
          <form noValidate onSubmit={onSubmit}>
            <p className={styles.lead}>Hiromeruで使うパスワードを設定してください。設定後、ログイン画面からログインできます。</p>
            <div className={styles.field}>
              <label htmlFor="new-password">新しいパスワード</label>
              <Input
                ref={passwordRef}
                id="new-password"
                type={isPasswordVisible ? "text" : "password"}
                autoComplete="new-password"
                value={password}
                disabled={isPending}
                aria-invalid={passwordError !== null}
                aria-describedby={passwordError ? "new-password-rule new-password-error" : "new-password-rule"}
                onChange={(event) => onPasswordChange(event.currentTarget.value)}
                trailingAction={<Button variant="ghost" size="small" onClick={onPasswordVisibilityToggle} disabled={isPending}>
                  {isPasswordVisible ? "隠す" : "表示"}
                </Button>}
              />
              <p id="new-password-rule" className={styles.rule}>{PASSWORD_RULE}</p>
              {passwordError ? <p id="new-password-error" className={styles.fieldError}>{passwordError}</p> : null}
            </div>
            <Button block type="submit" isLoading={isPending} loadingLabel="設定中">パスワードを設定</Button>
            {formError ? <p className={styles.formError} role="alert">{formError}</p> : null}
          </form>
        )}
      </main>
    </div>
  );
}
