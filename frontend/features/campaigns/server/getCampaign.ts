import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import type { CampaignDetailResponse } from "@/features/campaigns/types/campaign";

export function getCampaign(campaignId: number): Promise<CampaignDetailResponse> {
  return serverApiRequest<CampaignDetailResponse>(`/api/v1/campaigns/${campaignId}`);
}
