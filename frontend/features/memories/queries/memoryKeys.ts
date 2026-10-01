import type { MemoryListParams } from "@/features/memories/utils/memoryParams";

export const memoryKeys = {
  all: ["memories"] as const,
  lists: ["memories", "list"] as const,
  list: (params: MemoryListParams) => [...memoryKeys.lists, params] as const,
  campaigns: (id: number) => ["memories", id, "campaigns"] as const,
  posts: (id: number) => ["memories", id, "posts"] as const,
};
