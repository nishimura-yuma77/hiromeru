"use client";

import { useReducer } from "react";
import { useRouter } from "next/navigation";

import { useLogoutMutation } from "@/features/auth/queries/useLogoutMutation";

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

export function useLogoutController() {
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
      router.replace("/login");
      router.refresh();
    } catch {
      dispatch({ type: "failed" });
    }
  }

  return { ...state, onLogout };
}
