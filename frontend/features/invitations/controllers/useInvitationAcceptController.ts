"use client";

import { useReducer, useRef, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { acceptInvitation } from "@/features/invitations/api/acceptInvitation";
import {
  createInitialInvitationAcceptState,
  invitationAcceptReducer,
  validateNewPassword,
} from "@/features/invitations/state/invitationAcceptReducer";
import { ApiError } from "@/shared/api/ApiError";

export function useInvitationAcceptController(token: string | null) {
  const router = useRouter();
  const [state, dispatch] = useReducer(invitationAcceptReducer, token !== null, createInitialInvitationAcceptState);
  const passwordRef = useRef<HTMLInputElement>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.isPending || token === null) {
      return;
    }
    dispatch({ type: "submitStarted" });
    const passwordError = validateNewPassword(state.password);
    if (passwordError) {
      dispatch({ type: "validationFailed", passwordError });
      passwordRef.current?.focus();
      return;
    }
    try {
      const userType = await acceptInvitation(token, state.password);
      // 履歴を置き換え、トークン付きURLを残さない。種別に応じたログイン画面へ案内する。
      router.replace(userType === "admin" ? "/admin/login?registered=1" : "/login?registered=1");
    } catch (error) {
      if (error instanceof ApiError && error.code === "INVITATION_LINK_INVALID") {
        dispatch({ type: "linkRejected" });
        return;
      }
      if (error instanceof ApiError && error.code === "INVALID_ARGUMENT") {
        const message = error.fieldErrors.find((fieldError) => fieldError.field === "password")?.message;
        dispatch({ type: "validationFailed", passwordError: message ?? "入力内容を確認してください" });
        passwordRef.current?.focus();
        return;
      }
      dispatch({
        type: "submitFailed",
        message:
          error instanceof ApiError && error.code === "CSRF_VALIDATION_FAILED"
            ? "安全性を確認できませんでした。ページを再読み込みしてください"
            : "パスワードを設定できませんでした。時間をおいて、もう一度お試しください",
      });
    }
  }

  return {
    state,
    passwordRef,
    onSubmit,
    onPasswordChange: (password: string) => dispatch({ type: "passwordChanged", password }),
    onPasswordVisibilityToggle: () => dispatch({ type: "passwordVisibilityToggled" }),
  };
}
