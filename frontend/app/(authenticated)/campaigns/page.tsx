import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { CampaignList } from "@/features/campaigns/components/CampaignList/CampaignList";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import { listCampaigns } from "@/features/campaigns/server/listCampaigns";
import { parseCampaignListParams } from "@/features/campaigns/utils/campaignParams";
import { makeQueryClient } from "@/shared/api/queryClient";

type CampaignsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function CampaignsPage({ searchParams }: CampaignsPageProps) {
  const params = parseCampaignListParams(await searchParams);
  const response = await listCampaigns(params);
  const client = makeQueryClient();
  client.setQueryData(campaignKeys.list(params), response);
  return <HydrationBoundary state={dehydrate(client)}><CampaignList response={response} params={params} /></HydrationBoundary>;
}
