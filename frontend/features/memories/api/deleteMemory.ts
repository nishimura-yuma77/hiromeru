import { browserApiRequest } from "@/shared/api/browserApiClient";
import type { DeleteMemoryResponse } from "@/features/memories/types/memory";

export function deleteMemory(memoryId: number): Promise<DeleteMemoryResponse> {
  return browserApiRequest<DeleteMemoryResponse>(`/api/v1/memories/${memoryId}`, {
    method: "DELETE",
  });
}
