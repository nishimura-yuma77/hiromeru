import { CampaignList } from "@/features/campaigns/components/CampaignList/CampaignList";
import { listCampaigns } from "@/features/campaigns/server/listCampaigns";
import { parseCampaignListParams } from "@/features/campaigns/utils/campaignParams";

type CampaignsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CampaignsPage({ searchParams }: CampaignsPageProps) {
  const params = parseCampaignListParams(await searchParams);
  const response = await listCampaigns(params);
  return <CampaignList response={response} params={params} />;
}
