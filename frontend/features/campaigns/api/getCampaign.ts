import { browserApiRequest } from "@/shared/api/browserApiClient";
import type { CampaignDetailResponse } from "@/features/campaigns/types/campaign";

export function getCampaign(campaignId: number): Promise<CampaignDetailResponse> {
  return browserApiRequest<CampaignDetailResponse>(`/api/v1/campaigns/${campaignId}`, {});
}
