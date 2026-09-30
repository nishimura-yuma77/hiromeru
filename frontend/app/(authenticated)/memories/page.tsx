import { getCampaign } from "@/features/campaigns/server/getCampaign";
import { MemoryList } from "@/features/memories/components/MemoryList/MemoryList";
import { listMemories } from "@/features/memories/server/listMemories";
import { parseMemoryListParams } from "@/features/memories/utils/memoryParams";
import { ApiError } from "@/shared/api/ApiError";

type MemoriesPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MemoriesPage({ searchParams }: MemoriesPageProps) {
  const params = parseMemoryListParams(await searchParams);
  const campaignId = params.campaignId;
  const [response, selectedCampaign] = await Promise.all([
    listMemories(params),
    campaignId ? getCampaign(campaignId).then(({ campaign }) => ({ id: campaign.id, title: campaign.title })).catch((error: unknown) => {
      if (error instanceof ApiError && error.code === "CAMPAIGN_NOT_FOUND") return { id: campaignId, title: `施策ID ${campaignId}` };
      throw error;
    }) : Promise.resolve(null),
  ]);
  return <MemoryList response={response} params={params} selectedCampaign={selectedCampaign} />;
}
