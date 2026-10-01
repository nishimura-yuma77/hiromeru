"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { deleteMemory } from "@/features/memories/api/deleteMemory";
import { memoryKeys } from "@/features/memories/queries/memoryKeys";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import type { MemoryListResponse } from "@/features/memories/types/memory";

export function useDeleteMemoryMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (memoryId: number) => deleteMemory(memoryId),
    onSuccess: (_, memoryId) => {
      client.setQueriesData<MemoryListResponse>({ queryKey: memoryKeys.lists }, (current) => current
        ? { ...current, memories: current.memories.filter((memory) => memory.id !== memoryId) } : current);
      void client.invalidateQueries({ queryKey: memoryKeys.lists });
      void client.removeQueries({ queryKey: ["memories", memoryId] });
      void client.invalidateQueries({ queryKey: campaignKeys.details });
    },
  });
}
