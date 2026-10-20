"use client";

import { useEffect, useReducer, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";

import {
  useInviteUserMutation,
  useReactivateUserMutation,
  useResendInvitationMutation,
  useSuspendUserMutation,
  useUpdateUserMutation,
} from "@/features/users/queries/useUserMutations";
import { useUserListQuery } from "@/features/users/queries/userQueries";
import {
  initialUserManagementState,
  userManagementReducer,
  validateInviteEmail,
  validateUserName,
  type ConfirmKind,
} from "@/features/users/state/userManagementReducer";
import { parsePageParam, type CompanyUser, type UserType } from "@/features/users/types/user";
import { ApiError } from "@/shared/api/ApiError";

const SEND_FAILED_MESSAGE =
  "ユーザーは登録しましたが、招待メールを送信できませんでした。一覧から招待メールを再送してください";
const SEND_UNKNOWN_MESSAGE =
  "ユーザーは登録しましたが、招待メールの送信結果を確認できませんでした。届いていない場合は一覧から再送してください";

function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "処理を完了できませんでした。一覧を確認してから、もう一度お試しください";
  }
  switch (error.code) {
    case "USER_STATE_CONFLICT":
      return "ユーザーの状態が変わったため、この操作を行えませんでした。一覧を更新しました";
    case "USER_ROLE_CHANGE_FORBIDDEN":
      return "自分自身と責任者のユーザー種別は変更できません";
    case "USER_SUSPENSION_FORBIDDEN":
      return "自分自身と責任者は利用停止できません";
    case "ADMIN_USER_NOT_FOUND":
      return "ユーザーが見つかりませんでした。一覧を更新しました";
    case "ADMIN_FORBIDDEN":
      return "この操作を行う権限がありません";
  }
  if (error.kind === "network" || error.kind === "timeout") {
    return "処理結果を確認できませんでした。一覧で状態を確認してから、必要なら再度操作してください";
  }
  return "処理を完了できませんでした。一覧を確認してから、もう一度お試しください";
}

function isSendError(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    (error.code === "INVITATION_SEND_FAILED" || error.code === "INVITATION_SEND_OUTCOME_UNKNOWN")
  );
}

// 結果を決めつけられない失敗。自動で再送せず、一覧を再取得して保存済みの状態を確認させる。
function isOutcomeUnknown(error: unknown): boolean {
  return (
    !(error instanceof ApiError) ||
    error.code === "INTERNAL_ERROR" ||
    error.code === "HTTP_ERROR" ||
    error.kind === "network" ||
    error.kind === "timeout" ||
    error.kind === "parse"
  );
}

const OUTCOME_UNKNOWN_NOTICE =
  "処理結果を確認できませんでした。一覧で送信結果を確認し、届いていない場合は招待メールを再送してください";

function sendErrorMessage(error: ApiError, prefix: string): string {
  return error.code === "INVITATION_SEND_FAILED"
    ? `${prefix}招待メールを送信できませんでした。一覧から再送してください`
    : `${prefix}招待メールの送信結果を確認できませんでした。届いていない場合は一覧から再送してください`;
}

export function canChangeUserType(user: CompanyUser, currentUserId: number): boolean {
  return user.status === "active" && user.userId !== currentUserId && !user.isResponsible;
}

export function canSuspendUser(user: CompanyUser, currentUserId: number): boolean {
  return user.status !== "suspended" && user.userId !== currentUserId && !user.isResponsible;
}

export function useUserManagementController() {
  const searchParams = useSearchParams();
  const page = parsePageParam(searchParams.get("page"));
  const [state, dispatch] = useReducer(userManagementReducer, initialUserManagementState);
  const listQuery = useUserListQuery(page);
  const invite = useInviteUserMutation();
  const update = useUpdateUserMutation();
  const suspend = useSuspendUserMutation();
  const reactivate = useReactivateUserMutation();
  const resend = useResendInvitationMutation();

  const listError = listQuery.error;
  useEffect(() => {
    // 手入力や古いURLで範囲外のpageを開いた場合は先頭へ戻す（SCREEN_DESIGN SC-11）。
    if (listError instanceof ApiError && listError.code === "INVALID_ARGUMENT" && page !== 1) {
      window.history.replaceState(null, "", "/admin/users?page=1");
    }
  }, [listError, page]);

  const users = listQuery.data?.users ?? [];
  const operatingUserId = state.dialog.kind === "operate" ? state.dialog.userId : null;
  const selectedUser = users.find((user) => user.userId === operatingUserId) ?? null;

  function goToPage(next: number) {
    window.history.pushState(null, "", `/admin/users?page=${next}`);
  }

  async function submitInvite(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.dialog.kind !== "invite" || state.isPending) {
      return;
    }
    const { form } = state.dialog;
    const nameError = validateUserName(form.name);
    const emailError = validateInviteEmail(form.email);
    if (nameError || emailError) {
      dispatch({ type: "inviteValidationFailed", nameError, emailError });
      return;
    }
    dispatch({ type: "requestStarted" });
    try {
      await invite.mutateAsync({ userType: form.userType, name: form.name.trim(), email: form.email.trim() });
      dispatch({
        type: "requestSucceeded",
        notice: { tone: "success", message: "招待メールを送信しました（送信受付済み。配達完了を示すものではありません）" },
      });
    } catch (error) {
      if (isSendError(error)) {
        dispatch({
          type: "requestEndedWithNotice",
          notice: {
            tone: "error",
            message: error.code === "INVITATION_SEND_FAILED" ? SEND_FAILED_MESSAGE : SEND_UNKNOWN_MESSAGE,
          },
        });
        return;
      }
      if (error instanceof ApiError && error.code === "USER_INVITATION_CONFLICT") {
        dispatch({ type: "inviteValidationFailed", nameError: null, emailError: "このメールアドレスでは招待できません" });
        return;
      }
      if (isOutcomeUnknown(error)) {
        dispatch({ type: "requestEndedWithNotice", notice: { tone: "error", message: OUTCOME_UNKNOWN_NOTICE } });
        return;
      }
      if (error instanceof ApiError && error.code === "INVALID_ARGUMENT") {
        const fieldMessage = (field: string) =>
          error.fieldErrors.find((fieldError) => fieldError.field === field)?.message ?? null;
        dispatch({ type: "inviteValidationFailed", nameError: fieldMessage("name"), emailError: fieldMessage("email") });
        return;
      }
      dispatch({ type: "requestFailed", message: errorMessage(error), closeConfirm: false });
    }
  }

  function saveOperation() {
    if (state.dialog.kind !== "operate" || !selectedUser || state.isPending) {
      return;
    }
    const nameError = validateUserName(state.dialog.name);
    if (nameError) {
      dispatch({ type: "operateValidationFailed", nameError });
      return;
    }
    if (state.dialog.userType !== selectedUser.userType) {
      // 実際に種別が変わる場合だけ、旧ログインの失効を確認する。
      dispatch({ type: "confirmOpened", confirm: "roleChange" });
      return;
    }
    if (state.dialog.name.trim() === selectedUser.name) {
      dispatch({ type: "closed" });
      return;
    }
    void runUpdate(selectedUser.userId, state.dialog.name.trim(), undefined);
  }

  async function runUpdate(userId: number, name: string | undefined, userType: UserType | undefined) {
    dispatch({ type: "requestStarted" });
    try {
      await update.mutateAsync({ userId, name, userType });
      dispatch({
        type: "requestSucceeded",
        notice: {
          tone: "success",
          message: userType
            ? "ユーザー種別を変更しました。対象者は変更後の種別のログイン画面から再ログインします"
            : "表示名を更新しました",
        },
      });
    } catch (error) {
      dispatch({ type: "requestFailed", message: errorMessage(error), closeConfirm: true });
    }
  }

  async function confirm() {
    if (state.dialog.kind !== "operate" || !state.dialog.confirm || !selectedUser || state.isPending) {
      return;
    }
    const kind: ConfirmKind = state.dialog.confirm;
    const userId = selectedUser.userId;
    if (kind === "roleChange") {
      const name = state.dialog.name.trim();
      await runUpdate(userId, name === selectedUser.name ? undefined : name, state.dialog.userType);
      return;
    }
    dispatch({ type: "requestStarted" });
    try {
      if (kind === "suspend") {
        await suspend.mutateAsync(userId);
      } else if (kind === "reactivate") {
        await reactivate.mutateAsync(userId);
      } else {
        await resend.mutateAsync(userId);
      }
      const messages: Record<Exclude<ConfirmKind, "roleChange">, string> = {
        suspend: "利用停止しました。対象者の既存のログインと招待リンクは使えなくなりました",
        reactivate: "利用を再開し、招待メールを送信しました。本人がパスワードを設定すると利用中になります",
        resend: "招待メールを再送しました。以前のリンクは使えなくなりました",
      };
      dispatch({ type: "requestSucceeded", notice: { tone: "success", message: messages[kind] } });
    } catch (error) {
      if (isSendError(error)) {
        const prefix = kind === "reactivate" ? "利用を再開しましたが、" : "新しいリンクを発行しましたが、";
        dispatch({ type: "requestEndedWithNotice", notice: { tone: "error", message: sendErrorMessage(error, prefix) } });
        return;
      }
      if (kind !== "suspend" && isOutcomeUnknown(error)) {
        dispatch({ type: "requestEndedWithNotice", notice: { tone: "error", message: OUTCOME_UNKNOWN_NOTICE } });
        return;
      }
      dispatch({ type: "requestFailed", message: errorMessage(error), closeConfirm: true });
    }
  }

  return {
    state,
    page,
    list: listQuery.data ?? null,
    isListLoading: listQuery.isFetching,
    listError: listError ? errorMessage(listError) : null,
    selectedUser,
    goToPage,
    refetch: () => void listQuery.refetch(),
    openInvite: () => dispatch({ type: "inviteOpened" }),
    changeInvite: (field: "userType" | "name" | "email", value: string) =>
      dispatch({ type: "inviteChanged", field, value }),
    submitInvite,
    openOperation: (user: CompanyUser) => dispatch({ type: "operateOpened", user }),
    changeOperationName: (name: string) => dispatch({ type: "operateNameChanged", name }),
    changeOperationType: (userType: UserType) => dispatch({ type: "operateTypeChanged", userType }),
    saveOperation,
    openConfirm: (confirmKind: ConfirmKind) => dispatch({ type: "confirmOpened", confirm: confirmKind }),
    cancelConfirm: () => dispatch({ type: "confirmCancelled" }),
    confirm,
    close: () => dispatch({ type: "closed" }),
    dismissNotice: () => dispatch({ type: "noticeDismissed" }),
  };
}

export type UserManagementController = ReturnType<typeof useUserManagementController>;
