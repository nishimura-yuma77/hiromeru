import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import type { CampaignListResponse } from "@/features/campaigns/types/campaign";
import { campaignQuery, type CampaignListParams } from "@/features/campaigns/utils/campaignParams";

export function listCampaigns(params: CampaignListParams): Promise<CampaignListResponse> {
  return serverApiRequest<CampaignListResponse>(`/api/v1/campaigns?${campaignQuery(params)}`);
}
