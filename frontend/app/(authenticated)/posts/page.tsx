import { PostList } from "@/features/posts/components/PostList/PostList";
import { listPosts } from "@/features/posts/server/listPosts";
import { parsePostListParams } from "@/features/posts/utils/postParams";

type PostsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PostsPage({ searchParams }: PostsPageProps) {
  const params = parsePostListParams(await searchParams);
  const response = await listPosts(params);
  return <PostList response={response} params={params} />;
}
