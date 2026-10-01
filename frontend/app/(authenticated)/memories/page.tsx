import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getCampaign } from "@/features/campaigns/server/getCampaign";
import { MemoryList } from "@/features/memories/components/MemoryList/MemoryList";
import { memoryKeys } from "@/features/memories/queries/memoryKeys";
import { listMemories } from "@/features/memories/server/listMemories";
import { parseMemoryListParams } from "@/features/memories/utils/memoryParams";
import { ApiError } from "@/shared/api/ApiError";
import { makeQueryClient } from "@/shared/api/queryClient";

type MemoriesPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MemoriesPage({ searchParams }: MemoriesPageProps) {
  const params = parseMemoryListParams(await searchParams);
  const campaignId = params.campaignId;
  const [response, selectedCampaign] = await Promise.all([
    listMemories(params),
    campaignId ? getCampaign(campaignId).then(({ campaign }) => ({ id: campaign.id, title: campaign.title, archived_at: campaign.archived_at })).catch((error: unknown) => {
      if (error instanceof ApiError && error.code === "CAMPAIGN_NOT_FOUND") return { id: campaignId, title: `施策ID ${campaignId}`, archived_at: null };
      throw error;
    }) : Promise.resolve(null),
  ]);
  const client = makeQueryClient();
  client.setQueryData(memoryKeys.list(params), response);
  return <HydrationBoundary state={dehydrate(client)}><MemoryList response={response} params={params} selectedCampaign={selectedCampaign} /></HydrationBoundary>;
}
