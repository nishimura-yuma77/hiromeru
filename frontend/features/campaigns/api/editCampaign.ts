import { browserApiRequest } from "@/shared/api/browserApiClient";
import type {
  CampaignEditRequest,
  CampaignEditResponse,
} from "@/features/campaigns/types/campaign";

export function editCampaign(
  campaignId: number,
  request: CampaignEditRequest,
): Promise<CampaignEditResponse> {
  return browserApiRequest<CampaignEditResponse>(`/api/v1/campaigns/${campaignId}`, {
    method: "PUT",
    body: request,
  });
}
