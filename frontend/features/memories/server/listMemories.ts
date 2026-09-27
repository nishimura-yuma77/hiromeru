import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import type { MemoryListResponse } from "@/features/memories/types/memory";
import { memoryApiQuery, type MemoryListParams } from "@/features/memories/utils/memoryParams";

export function listMemories(params: MemoryListParams): Promise<MemoryListResponse> {
  return serverApiRequest<MemoryListResponse>(`/api/v1/memories?${memoryApiQuery(params)}`);
}
