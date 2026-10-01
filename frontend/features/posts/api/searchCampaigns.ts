import { browserApiRequest } from "@/shared/api/browserApiClient";

export type CampaignOption = { id: number; title: string; archived_at: string | null };

export function searchCampaigns(query: string, signal: AbortSignal) {
  const params = new URLSearchParams({ limit: "20" });
  if (query) params.set("query", query);
  return browserApiRequest<{ campaigns: CampaignOption[] }>(`/api/v1/campaigns?${params}`, {
    method: "GET",
    signal,
  });
}
