import { browserApiRequest } from "@/shared/api/browserApiClient";
import type {
  MemoryCampaignListResponse,
  MemoryPostListResponse,
} from "@/features/memories/types/memory";

function relationPath(memoryId: number, relation: "campaigns" | "posts", cursor: string) {
  const query = new URLSearchParams({ limit: "20", cursor });
  return `/api/v1/memories/${memoryId}/${relation}?${query}` as `/api/${string}`;
}

export function listMemoryCampaigns(memoryId: number, cursor: string) {
  return browserApiRequest<MemoryCampaignListResponse>(relationPath(memoryId, "campaigns", cursor), {
    method: "GET",
  });
}

export function listMemoryPosts(memoryId: number, cursor: string) {
  return browserApiRequest<MemoryPostListResponse>(relationPath(memoryId, "posts", cursor), {
    method: "GET",
  });
}
