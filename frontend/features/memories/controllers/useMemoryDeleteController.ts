"use client";

import { useReducer } from "react";
import { useRouter } from "next/navigation";

import { deleteMemory } from "@/features/memories/api/deleteMemory";
import {
  initialMemoryDeleteState,
  memoryDeleteReducer,
} from "@/features/memories/state/memoryDeleteReducer";

export function useMemoryDeleteController() {
  const router = useRouter();
  const [state, dispatch] = useReducer(memoryDeleteReducer, initialMemoryDeleteState);

  async function confirmDelete() {
    const memoryId = state.selectedId;
    if (memoryId === null || state.isPending) return;
    dispatch({ type: "deleteStarted" });
    try {
      await deleteMemory(memoryId);
      dispatch({ type: "deleteSucceeded", memoryId });
      router.refresh();
    } catch {
      dispatch({ type: "deleteFailed", message: "記憶を削除できませんでした。もう一度お試しください。" });
    }
  }

  return {
    state,
    open: (memoryId: number) => dispatch({ type: "confirmationOpened", memoryId }),
    close: () => dispatch({ type: "confirmationClosed" }),
    confirmDelete,
  };
}
