"use client";

import { useReducer } from "react";
import { useRouter } from "next/navigation";

import { useLogoutMutation } from "@/features/auth/queries/useLogoutMutation";
import { forgetLoginPortal } from "@/shared/lib/loginPortal";

type LogoutState = { isPending: boolean; error: string | null };
type LogoutEvent = { type: "started" } | { type: "failed" };

function reducer(state: LogoutState, event: LogoutEvent): LogoutState {
  switch (event.type) {
    case "started":
      return { isPending: true, error: null };
    case "failed":
      return { ...state, isPending: false, error: "ログアウトできませんでした。もう一度お試しください" };
  }
}

export function useLogoutController(loginPath: "/login" | "/admin/login" = "/login") {
  const router = useRouter();
  const [state, dispatch] = useReducer(reducer, { isPending: false, error: null });
  const mutation = useLogoutMutation();

  async function onLogout() {
    if (state.isPending) {
      return;
    }
    dispatch({ type: "started" });
    try {
      await mutation.mutateAsync();
      // 明示的なログアウトでは入口ヒントも削除する。認証CookieはAPIが削除する。
      forgetLoginPortal();
      router.replace(loginPath);
      router.refresh();
    } catch {
      dispatch({ type: "failed" });
    }
  }

  return { ...state, onLogout };
}
