"use client";

import { useReducer, useRef, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { login } from "@/features/auth/api/authClient";
import {
  createInitialLoginState,
  loginReducer,
  validateEmail,
  validatePassword,
} from "@/features/auth/state/loginState";
import { ApiError } from "@/shared/api/ApiError";

type UseLoginControllerOptions = {
  nextPath: string;
  initialFormError: string | null;
};

function loginErrorMessage(error: ApiError): { message: string; shouldReload: boolean } {
  if (error.status === 429) {
    return { message: "試行回数が上限を超えました。しばらくしてから再試行してください", shouldReload: false };
  }
  if (error.code === "INVALID_ARGUMENT") {
    return { message: "入力内容を確認して、もう一度ログインしてください", shouldReload: false };
  }
  if (error.code === "CSRF_VALIDATION_FAILED") {
    return { message: "安全性を確認できなかったため、ログインできませんでした。ページを再読み込みしてください", shouldReload: true };
  }
  if (error.kind === "network") {
    return { message: "通信できませんでした。通信環境を確認して、もう一度お試しください", shouldReload: false };
  }
  if (error.kind === "timeout") {
    return { message: "ログイン処理が完了しませんでした。時間をおいて、もう一度お試しください", shouldReload: false };
  }
  return { message: "ログインできませんでした。時間をおいて、もう一度お試しください", shouldReload: false };
}

export function useLoginController({ nextPath, initialFormError }: UseLoginControllerOptions) {
  const router = useRouter();
  const [state, dispatch] = useReducer(loginReducer, initialFormError, createInitialLoginState);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const formErrorRef = useRef<HTMLDivElement>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (state.isPending) {
      return;
    }

    dispatch({ type: "loginStarted" });
    const email = state.email.trim();
    const emailError = validateEmail(email);
    const passwordError = validatePassword(state.password);
    if (emailError || passwordError) {
      dispatch({ type: "validationFailed", emailError, passwordError });
      (emailError ? emailRef : passwordRef).current?.focus();
      return;
    }

    try {
      await login({ email, password: state.password });
      router.replace(nextPath);
      router.refresh();
    } catch (error) {
      if (error instanceof ApiError && error.code === "INVALID_CREDENTIALS") {
        dispatch({ type: "credentialsRejected" });
        emailRef.current?.focus();
        return;
      }

      const displayError = loginErrorMessage(
        error instanceof ApiError
          ? error
          : new ApiError({ kind: "network", message: "APIへ接続できませんでした。" }),
      );
      dispatch({ type: "loginFailed", ...displayError });
      requestAnimationFrame(() => formErrorRef.current?.focus());
    }
  }

  return {
    state,
    emailRef,
    passwordRef,
    formErrorRef,
    onSubmit,
    onEmailChange: (email: string) => dispatch({ type: "emailChanged", email }),
    onPasswordChange: (password: string) => dispatch({ type: "passwordChanged", password }),
    onPasswordVisibilityToggle: () => dispatch({ type: "passwordVisibilityToggled" }),
    onReload: () => window.location.reload(),
  };
}
