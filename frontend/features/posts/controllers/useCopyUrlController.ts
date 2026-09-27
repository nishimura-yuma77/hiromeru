"use client";

import { useReducer } from "react";

import { copyReducer, initialCopyState } from "@/features/posts/state/copyReducer";

export function useCopyUrlController() {
  const [state, dispatch] = useReducer(copyReducer, initialCopyState);

  async function copy(field: string, url: string) {
    try {
      await navigator.clipboard.writeText(url);
      dispatch({ type: "copySucceeded", field });
    } catch {
      dispatch({ type: "copyFailed" });
    }
  }

  return { state, copy };
}
