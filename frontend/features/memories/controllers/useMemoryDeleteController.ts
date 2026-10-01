"use client";

import { useReducer } from "react";

import { useDeleteMemoryMutation } from "@/features/memories/queries/useDeleteMemoryMutation";
import {
  initialMemoryDeleteState,
  memoryDeleteReducer,
} from "@/features/memories/state/memoryDeleteReducer";

export function useMemoryDeleteController(onDeleted: (memoryId: number) => void) {
  const [state, dispatch] = useReducer(memoryDeleteReducer, initialMemoryDeleteState);
  const deleteMutation = useDeleteMemoryMutation();

  async function confirmDelete() {
    const memoryId = state.selectedId;
    if (memoryId === null || state.isPending) return;
    dispatch({ type: "deleteStarted" });
    try {
      await deleteMutation.mutateAsync(memoryId);
      dispatch({ type: "deleteSucceeded", memoryId });
      onDeleted(memoryId);
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
