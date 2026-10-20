import type { CompanyUser, UserType } from "@/features/users/types/user";

export type ConfirmKind = "roleChange" | "suspend" | "reactivate" | "resend";

export type InviteForm = {
  userType: UserType;
  name: string;
  email: string;
  nameError: string | null;
  emailError: string | null;
};

export type Dialog =
  | { kind: "none" }
  | { kind: "invite"; form: InviteForm }
  | {
      kind: "operate";
      userId: number;
      name: string;
      nameError: string | null;
      userType: UserType;
      confirm: ConfirmKind | null;
    };

export type Notice = { tone: "success" | "error"; message: string };

export type UserManagementState = {
  dialog: Dialog;
  isPending: boolean;
  dialogError: string | null;
  notice: Notice | null;
};

export type UserManagementEvent =
  | { type: "inviteOpened" }
  | { type: "inviteChanged"; field: "userType" | "name" | "email"; value: string }
  | { type: "inviteValidationFailed"; nameError: string | null; emailError: string | null }
  | { type: "operateOpened"; user: CompanyUser }
  | { type: "operateNameChanged"; name: string }
  | { type: "operateTypeChanged"; userType: UserType }
  | { type: "operateValidationFailed"; nameError: string }
  | { type: "confirmOpened"; confirm: ConfirmKind }
  | { type: "confirmCancelled" }
  | { type: "closed" }
  | { type: "requestStarted" }
  | { type: "requestFailed"; message: string; closeConfirm: boolean }
  | { type: "requestSucceeded"; notice: Notice }
  | { type: "requestEndedWithNotice"; notice: Notice }
  | { type: "noticeDismissed" };

export const initialUserManagementState: UserManagementState = {
  dialog: { kind: "none" },
  isPending: false,
  dialogError: null,
  notice: null,
};

const MAX_NAME_LENGTH = 255;

export function validateUserName(name: string): string | null {
  const trimmed = name.trim();
  if (trimmed.length === 0) {
    return "表示名を入力してください";
  }
  return trimmed.length > MAX_NAME_LENGTH ? "表示名は255文字以内で入力してください" : null;
}

export function validateInviteEmail(email: string): string | null {
  const trimmed = email.trim();
  if (trimmed.length === 0) {
    return "メールアドレスを入力してください";
  }
  if (trimmed.length > MAX_NAME_LENGTH) {
    return "メールアドレスは255文字以内で入力してください";
  }
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed) ? null : "メールアドレスの形式で入力してください";
}

function asUserType(value: string): UserType {
  return value === "admin" ? "admin" : "marketer";
}

export function userManagementReducer(
  state: UserManagementState,
  event: UserManagementEvent,
): UserManagementState {
  switch (event.type) {
    case "inviteOpened":
      return {
        ...state,
        dialogError: null,
        dialog: {
          kind: "invite",
          form: { userType: "marketer", name: "", email: "", nameError: null, emailError: null },
        },
      };
    case "inviteChanged": {
      if (state.dialog.kind !== "invite") {
        return state;
      }
      const form = state.dialog.form;
      const next =
        event.field === "userType"
          ? { ...form, userType: asUserType(event.value) }
          : event.field === "name"
            ? { ...form, name: event.value, nameError: form.nameError ? validateUserName(event.value) : null }
            : { ...form, email: event.value, emailError: form.emailError ? validateInviteEmail(event.value) : null };
      return { ...state, dialog: { kind: "invite", form: next } };
    }
    case "inviteValidationFailed":
      if (state.dialog.kind !== "invite") {
        return state;
      }
      return {
        ...state,
        isPending: false,
        dialog: {
          kind: "invite",
          form: { ...state.dialog.form, nameError: event.nameError, emailError: event.emailError },
        },
      };
    case "operateOpened":
      return {
        ...state,
        dialogError: null,
        dialog: {
          kind: "operate",
          userId: event.user.userId,
          name: event.user.name,
          nameError: null,
          userType: event.user.userType,
          confirm: null,
        },
      };
    case "operateNameChanged":
      if (state.dialog.kind !== "operate") {
        return state;
      }
      return {
        ...state,
        dialog: {
          ...state.dialog,
          name: event.name,
          nameError: state.dialog.nameError ? validateUserName(event.name) : null,
        },
      };
    case "operateTypeChanged":
      if (state.dialog.kind !== "operate") {
        return state;
      }
      return { ...state, dialog: { ...state.dialog, userType: event.userType } };
    case "operateValidationFailed":
      if (state.dialog.kind !== "operate") {
        return state;
      }
      return { ...state, dialog: { ...state.dialog, nameError: event.nameError } };
    case "confirmOpened":
      if (state.dialog.kind !== "operate") {
        return state;
      }
      return { ...state, dialogError: null, dialog: { ...state.dialog, confirm: event.confirm } };
    case "confirmCancelled":
      // 確認をキャンセルしても、操作用モーダルの編集内容は保持する。
      if (state.dialog.kind !== "operate") {
        return state;
      }
      return { ...state, dialog: { ...state.dialog, confirm: null } };
    case "closed":
      return { ...state, dialog: { kind: "none" }, dialogError: null, isPending: false };
    case "requestStarted":
      return { ...state, isPending: true, dialogError: null, notice: null };
    case "requestFailed":
      return {
        ...state,
        isPending: false,
        dialogError: event.message,
        dialog:
          event.closeConfirm && state.dialog.kind === "operate"
            ? { ...state.dialog, confirm: null }
            : state.dialog,
      };
    case "requestSucceeded":
    case "requestEndedWithNotice":
      return {
        ...state,
        isPending: false,
        dialogError: null,
        dialog: { kind: "none" },
        notice: event.notice,
      };
    case "noticeDismissed":
      return { ...state, notice: null };
  }
}
