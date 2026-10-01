import { browserApiRequest } from "@/shared/api/browserApiClient";
import type { MemoryListResponse } from "@/features/memories/types/memory";
import { memoryApiQuery, type MemoryListParams } from "@/features/memories/utils/memoryParams";

export function listMemoriesBrowser(params: MemoryListParams, signal: AbortSignal) {
  return browserApiRequest<MemoryListResponse>(`/api/v1/memories?${memoryApiQuery(params)}`, { method: "GET", signal });
}
