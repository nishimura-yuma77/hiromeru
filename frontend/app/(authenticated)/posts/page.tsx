import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { getCampaign } from "@/features/campaigns/server/getCampaign";
import { PostList } from "@/features/posts/components/PostList/PostList";
import { postKeys } from "@/features/posts/queries/postKeys";
import { listPosts } from "@/features/posts/server/listPosts";
import { parsePostListParams } from "@/features/posts/utils/postParams";
import { makeQueryClient } from "@/shared/api/queryClient";

type PostsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PostsPage({ searchParams }: PostsPageProps) {
  const params = parsePostListParams(await searchParams);
  const [response, selectedCampaign] = await Promise.all([
    listPosts(params),
    params.campaignId ? getCampaign(params.campaignId).then(({ campaign }) => ({
      id: campaign.id,
      title: campaign.title,
      archived_at: campaign.archived_at,
    })) : Promise.resolve(null),
  ]);
  const client = makeQueryClient();
  client.setQueryData(postKeys.list(params), response);
  return <HydrationBoundary state={dehydrate(client)}><PostList response={response} params={params} selectedCampaign={selectedCampaign} /></HydrationBoundary>;
}
