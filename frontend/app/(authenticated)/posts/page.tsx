import { getCampaign } from "@/features/campaigns/server/getCampaign";
import { PostList } from "@/features/posts/components/PostList/PostList";
import { listPosts } from "@/features/posts/server/listPosts";
import { parsePostListParams } from "@/features/posts/utils/postParams";

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
  return <PostList response={response} params={params} selectedCampaign={selectedCampaign} />;
}
