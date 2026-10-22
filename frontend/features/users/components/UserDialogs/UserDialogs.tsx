import type { FormEvent } from "react";

import type { ConfirmKind, Dialog, InviteForm } from "@/features/users/state/userManagementReducer";
import type { CompanyUser, UserType } from "@/features/users/types/user";
import { Button } from "@/shared/components/Button/Button";
import { Input } from "@/shared/components/Input/Input";

import styles from "./UserDialogs.module.scss";

type UserDialogsProps = {
  dialog: Dialog;
  selectedUser: CompanyUser | null;
  canChangeType: boolean;
  canSuspend: boolean;
  isPending: boolean;
  dialogError: string | null;
  onClose: () => void;
  onInviteChange: (field: "userType" | "name" | "email", value: string) => void;
  onInviteSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onNameChange: (name: string) => void;
  onTypeChange: (userType: UserType) => void;
  onSave: () => void;
  onOpenConfirm: (kind: ConfirmKind) => void;
  onCancelConfirm: () => void;
  onConfirm: () => void;
};

const TYPE_LABELS: Record<UserType, string> = { admin: "管理ユーザー", marketer: "マーケターユーザー" };

function UserTypeField({ name, value, disabled, onChange }: { name: string; value: UserType; disabled: boolean; onChange: (value: UserType) => void }) {
  return (
    <fieldset className={styles.typeField} disabled={disabled}>
      <legend>ユーザー種別</legend>
      {(["marketer", "admin"] as const).map((type) => (
        <label key={type} className={styles.radio}>
          <input type="radio" name={name} value={type} checked={value === type} onChange={() => onChange(type)} />
          <span>{TYPE_LABELS[type]}</span>
        </label>
      ))}
    </fieldset>
  );
}

function InviteDialog({ form, isPending, error, onClose, onChange, onSubmit }: {
  form: InviteForm;
  isPending: boolean;
  error: string | null;
  onClose: () => void;
  onChange: UserDialogsProps["onInviteChange"];
  onSubmit: UserDialogsProps["onInviteSubmit"];
}) {
  return (
    <div className={styles.backdrop} role="presentation">
      <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="invite-title">
        <h2 id="invite-title">ユーザーを招待</h2>
        <p className={styles.lead}>招待メールのリンクは発行から1時間有効です。本人がパスワードを設定すると利用を開始できます。</p>
        <form noValidate onSubmit={onSubmit}>
          <UserTypeField name="invite-user-type" value={form.userType} disabled={isPending} onChange={(value) => onChange("userType", value)} />
          <div className={styles.field}>
            <label htmlFor="invite-name">表示名</label>
            <Input
              id="invite-name"
              value={form.name}
              autoFocus
              disabled={isPending}
              aria-invalid={form.nameError !== null}
              aria-describedby={form.nameError ? "invite-name-error" : undefined}
              onChange={(event) => onChange("name", event.currentTarget.value)}
            />
            {form.nameError ? <p id="invite-name-error" className={styles.fieldError}>{form.nameError}</p> : null}
          </div>
          <div className={styles.field}>
            <label htmlFor="invite-email">メールアドレス</label>
            <Input
              id="invite-email"
              type="email"
              inputMode="email"
              autoComplete="off"
              value={form.email}
              disabled={isPending}
              aria-invalid={form.emailError !== null}
              aria-describedby={form.emailError ? "invite-email-error" : undefined}
              onChange={(event) => onChange("email", event.currentTarget.value)}
            />
            {form.emailError ? <p id="invite-email-error" className={styles.fieldError}>{form.emailError}</p> : null}
          </div>
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
          <div className={styles.actions}>
            <Button variant="secondary" onClick={onClose} disabled={isPending}>キャンセル</Button>
            <Button type="submit" isLoading={isPending} loadingLabel="送信中">招待メールを送信</Button>
          </div>
        </form>
      </section>
    </div>
  );
}

function confirmCopy(kind: ConfirmKind, user: CompanyUser, nextType: UserType): { title: string; body: string; action: string; danger: boolean } {
  switch (kind) {
    case "roleChange":
      return {
        title: "ユーザー種別を変更しますか？",
        body: `${user.name}さんの種別を「${TYPE_LABELS[user.userType]}」から「${TYPE_LABELS[nextType]}」へ変更します。対象者の現在のログインは失効し、変更後の種別のログイン画面から再ログインが必要になります。会話履歴とパスワードは維持されます。`,
        action: "種別を変更する",
        danger: false,
      };
    case "suspend":
      return {
        title: "利用を停止しますか？",
        body: `${user.name}さんの現在のログインと未使用の招待リンクを直ちに失効させます。再開すると新しい招待メールを送り、本人がパスワードを設定し直すまでログインできません。`,
        action: "利用停止する",
        danger: true,
      };
    case "reactivate":
      return {
        title: "利用を再開しますか？",
        body: `${user.name}さんを招待中に戻し、新しい招待メールを送ります。本人が新しいパスワードを設定するまでログインできません。`,
        action: "再開して招待メールを送る",
        danger: false,
      };
    case "resend":
      return {
        title: "招待メールを再送しますか？",
        body: `${user.name}さんの以前の招待リンクを無効にし、新しいリンクを送ります。`,
        action: "再送する",
        danger: false,
      };
  }
}

function OperationDialog({ dialog, user, canChangeType, canSuspend, isPending, error, onClose, onNameChange, onTypeChange, onSave, onOpenConfirm }: {
  dialog: Extract<Dialog, { kind: "operate" }>;
  user: CompanyUser;
  canChangeType: boolean;
  canSuspend: boolean;
  isPending: boolean;
  error: string | null;
  onClose: () => void;
  onNameChange: (name: string) => void;
  onTypeChange: (userType: UserType) => void;
  onSave: () => void;
  onOpenConfirm: (kind: ConfirmKind) => void;
}) {
  const confirming = dialog.confirm !== null;
  return (
    <div className={styles.backdrop} role="presentation">
      <section className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby="operate-title" inert={confirming ? true : undefined}>
        <h2 id="operate-title">ユーザーを編集</h2>
        <p className={styles.lead}>{user.email}</p>
        <form noValidate onSubmit={(event) => { event.preventDefault(); onSave(); }}>
          <div className={styles.field}>
            <label htmlFor="operate-name">表示名</label>
            <Input
              id="operate-name"
              value={dialog.name}
              autoFocus
              disabled={isPending}
              aria-invalid={dialog.nameError !== null}
              aria-describedby={dialog.nameError ? "operate-name-error" : undefined}
              onChange={(event) => onNameChange(event.currentTarget.value)}
            />
            {dialog.nameError ? <p id="operate-name-error" className={styles.fieldError}>{dialog.nameError}</p> : null}
          </div>
          {canChangeType ? (
            <UserTypeField name="operate-user-type" value={dialog.userType} disabled={isPending} onChange={onTypeChange} />
          ) : (
            <div className={styles.readonly}>
              <p className={styles.readonlyLabel}>ユーザー種別</p>
              <p>{TYPE_LABELS[user.userType]}</p>
              <p className={styles.hint}>自分自身・責任者・招待中・利用停止中のユーザーの種別は変更できません</p>
            </div>
          )}
          {error ? <p className={styles.error} role="alert">{error}</p> : null}
          <div className={styles.actions}>
            <Button variant="secondary" onClick={onClose} disabled={isPending}>閉じる</Button>
            <Button type="submit" isLoading={isPending && !confirming} loadingLabel="保存中">保存</Button>
          </div>
        </form>

        <div className={styles.stateActions}>
          <h3>利用状態</h3>
          {user.status === "invited" ? <Button variant="secondary" disabled={isPending} onClick={() => onOpenConfirm("resend")}>招待メールを再送</Button> : null}
          {user.status === "suspended" ? <Button variant="secondary" disabled={isPending} onClick={() => onOpenConfirm("reactivate")}>利用を再開</Button> : null}
          {canSuspend ? <Button variant="danger" disabled={isPending} onClick={() => onOpenConfirm("suspend")}>利用停止</Button> : null}
          {!canSuspend && user.status !== "suspended" ? <p className={styles.hint}>自分自身と責任者は利用停止できません</p> : null}
        </div>
      </section>
    </div>
  );
}

function ConfirmDialog({ kind, user, nextType, isPending, error, onCancel, onConfirm }: {
  kind: ConfirmKind;
  user: CompanyUser;
  nextType: UserType;
  isPending: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const copy = confirmCopy(kind, user, nextType);
  return (
    <div className={styles.backdrop} role="presentation">
      <section className={styles.confirm} role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description">
        <h2 id="confirm-title">{copy.title}</h2>
        <p id="confirm-description" className={styles.lead}>{copy.body}</p>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        <div className={styles.actions}>
          <Button variant="secondary" onClick={onCancel} disabled={isPending} autoFocus>キャンセル</Button>
          <Button variant={copy.danger ? "danger" : "primary"} onClick={onConfirm} isLoading={isPending} loadingLabel="処理中">{copy.action}</Button>
        </div>
      </section>
    </div>
  );
}

export function UserDialogs(props: UserDialogsProps) {
  const { dialog } = props;
  if (dialog.kind === "invite") {
    return (
      <InviteDialog
        form={dialog.form}
        isPending={props.isPending}
        error={props.dialogError}
        onClose={props.onClose}
        onChange={props.onInviteChange}
        onSubmit={props.onInviteSubmit}
      />
    );
  }
  if (dialog.kind === "operate" && props.selectedUser) {
    return (
      <>
        <OperationDialog
          dialog={dialog}
          user={props.selectedUser}
          canChangeType={props.canChangeType}
          canSuspend={props.canSuspend}
          isPending={props.isPending}
          error={dialog.confirm ? null : props.dialogError}
          onClose={props.onClose}
          onNameChange={props.onNameChange}
          onTypeChange={props.onTypeChange}
          onSave={props.onSave}
          onOpenConfirm={props.onOpenConfirm}
        />
        {dialog.confirm ? (
          <ConfirmDialog
            kind={dialog.confirm}
            user={props.selectedUser}
            nextType={dialog.userType}
            isPending={props.isPending}
            error={props.dialogError}
            onCancel={props.onCancelConfirm}
            onConfirm={props.onConfirm}
          />
        ) : null}
      </>
    );
  }
  return null;
}
