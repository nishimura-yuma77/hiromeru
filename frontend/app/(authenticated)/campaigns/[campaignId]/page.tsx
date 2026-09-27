import { notFound } from "next/navigation";
import { ApiError } from "@/shared/api/ApiError";

import { CampaignDetail } from "@/features/campaigns/components/CampaignDetail/CampaignDetail";
import { getCampaign } from "@/features/campaigns/server/getCampaign";
import { parsePositiveId } from "@/features/campaigns/utils/campaignParams";

type CampaignPageProps = { params: Promise<{ campaignId: string }> };

export default async function CampaignPage({ params }: CampaignPageProps) {
  const campaignId = parsePositiveId((await params).campaignId);
  if (campaignId === null) notFound();
  let detail;
  try {
    detail = await getCampaign(campaignId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "CAMPAIGN_NOT_FOUND") notFound();
    throw error;
  }
  return <CampaignDetail key={detail.campaign.updated_at} detail={detail} />;
}
