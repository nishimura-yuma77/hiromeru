import { browserApiRequest } from "@/shared/api/browserApiClient";
import type { CampaignListResponse } from "@/features/campaigns/types/campaign";
import { campaignQuery, type CampaignListParams } from "@/features/campaigns/utils/campaignParams";

export function listCampaignsBrowser(params: CampaignListParams, signal: AbortSignal) {
  return browserApiRequest<CampaignListResponse>(`/api/v1/campaigns?${campaignQuery(params)}`, { method: "GET", signal });
}
