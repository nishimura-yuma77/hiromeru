import type { ReactNode } from "react";

import type { Notice } from "@/features/users/state/userManagementReducer";
import type { CompanyUser, CompanyUserPage, EmailStatus, UserStatus } from "@/features/users/types/user";
import { Button } from "@/shared/components/Button/Button";

import styles from "./UserManagementView.module.scss";

type UserManagementViewProps = {
  list: CompanyUserPage | null;
  currentUserId: number;
  isLoading: boolean;
  listError: string | null;
  notice: Notice | null;
  dialogs: ReactNode;
  onInvite: () => void;
  onOperate: (user: CompanyUser) => void;
  onPage: (page: number) => void;
  onRetry: () => void;
  onDismissNotice: () => void;
};

const STATUS_LABELS: Record<UserStatus, string> = {
  invited: "招待中",
  active: "利用中",
  suspended: "利用停止中",
};

// 送信受付は配達完了を意味しない。pendingのまま結果を確認できない場合も結果不明として表示する。
const EMAIL_STATUS_LABELS: Record<EmailStatus, string> = {
  accepted: "送信受付済み",
  failed: "送信失敗",
  outcome_unknown: "送信結果を確認できませんでした",
  pending: "送信結果を確認できませんでした",
};

export function emailStatusLabel(status: EmailStatus | null): string {
  return status === null ? "送信なし" : EMAIL_STATUS_LABELS[status];
}

export function userTypeLabel(user: Pick<CompanyUser, "userType">): string {
  return user.userType === "admin" ? "管理ユーザー" : "マーケターユーザー";
}

function pageNumbers(page: number, totalPages: number): number[] {
  const first = Math.max(1, page - 2);
  const last = Math.min(totalPages, page + 2);
  return Array.from({ length: Math.max(0, last - first + 1) }, (_, index) => first + index);
}

function Pagination({ page, totalPages, disabled, onPage }: { page: number; totalPages: number; disabled: boolean; onPage: (page: number) => void }) {
  if (totalPages < 1) {
    return null;
  }
  const atFirst = page <= 1;
  const atLast = page >= totalPages;
  return (
    <nav className={styles.pagination} aria-label="ユーザー一覧のページ移動">
      <Button variant="ghost" size="small" disabled={disabled || atFirst} onClick={() => onPage(1)}>先頭</Button>
      <Button variant="ghost" size="small" disabled={disabled || atFirst} onClick={() => onPage(page - 1)}>前へ</Button>
      {pageNumbers(page, totalPages).map((number) => (
        <Button
          key={number}
          variant={number === page ? "primary" : "ghost"}
          size="small"
          disabled={disabled || number === page}
          aria-current={number === page ? "page" : undefined}
          aria-label={`${number}ページ目`}
          onClick={() => onPage(number)}
        >
          {String(number)}
        </Button>
      ))}
      <Button variant="ghost" size="small" disabled={disabled || atLast} onClick={() => onPage(page + 1)}>次へ</Button>
      <Button variant="ghost" size="small" disabled={disabled || atLast} onClick={() => onPage(totalPages)}>最後</Button>
    </nav>
  );
}

export function UserManagementView({
  list,
  currentUserId,
  isLoading,
  listError,
  notice,
  dialogs,
  onInvite,
  onOperate,
  onPage,
  onRetry,
  onDismissNotice,
}: UserManagementViewProps) {
  return (
    <section className={styles.page} aria-labelledby="users-title">
      <header className={styles.header}>
        <div>
          <h1 id="users-title">ユーザー管理</h1>
          <p className={styles.description}>自社の管理ユーザー・マーケターユーザーを招待し、利用状態を管理します。</p>
        </div>
        <Button onClick={onInvite}>新規招待</Button>
      </header>

      {notice ? (
        <div className={notice.tone === "error" ? styles.noticeError : styles.notice} role={notice.tone === "error" ? "alert" : "status"}>
          <p>{notice.message}</p>
          <Button variant="ghost" size="small" onClick={onDismissNotice}>閉じる</Button>
        </div>
      ) : null}

      {listError && !list ? (
        <div className={styles.listError} role="alert">
          <p>{listError}</p>
          <Button variant="secondary" size="small" onClick={onRetry}>再読み込み</Button>
        </div>
      ) : null}

      {list ? (
        <>
          <p className={styles.summary} aria-live="polite">
            全{list.totalCount}件{list.totalPages > 0 ? `（${list.page} / ${list.totalPages}ページ）` : ""}
            {isLoading ? "・更新中" : ""}
          </p>
          {list.users.length === 0 ? (
            <p className={styles.empty}>ユーザーがいません。</p>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">ID</th>
                    <th scope="col">表示名</th>
                    <th scope="col">メールアドレス</th>
                    <th scope="col">種別</th>
                    <th scope="col">利用状態</th>
                    <th scope="col">招待メール</th>
                    <th scope="col"><span className={styles.visuallyHidden}>操作</span></th>
                  </tr>
                </thead>
                <tbody>
                  {list.users.map((user) => (
                    <tr key={user.userId}>
                      <td className={styles.id}>{user.userId}</td>
                      <td>
                        <span className={styles.name}>{user.name}</span>
                        {user.isResponsible ? <span className={styles.responsible}>責任者</span> : null}
                        {user.userId === currentUserId ? <span className={styles.self}>あなた</span> : null}
                      </td>
                      <td className={styles.email}>{user.email}</td>
                      <td>{userTypeLabel(user)}</td>
                      <td><span className={styles[`status_${user.status}`]}>{STATUS_LABELS[user.status]}</span></td>
                      <td className={user.emailStatus === "failed" || user.emailStatus === "outcome_unknown" || user.emailStatus === "pending" ? styles.emailWarning : undefined}>
                        {emailStatusLabel(user.emailStatus)}
                      </td>
                      <td>
                        <Button variant="secondary" size="small" onClick={() => onOperate(user)} aria-label={`${user.name}を操作する`}>操作</Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={list.page} totalPages={list.totalPages} disabled={isLoading} onPage={onPage} />
        </>
      ) : null}

      {dialogs}
    </section>
  );
}
