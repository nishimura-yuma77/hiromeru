import { notFound } from "next/navigation";
import { ApiError } from "@/shared/api/ApiError";

import { PostDetail } from "@/features/posts/components/PostDetail/PostDetail";
import { getPost } from "@/features/posts/server/getPost";
import { parsePositiveId, safePostsReturnTo } from "@/features/posts/utils/postParams";

type PostPageProps = {
  params: Promise<{ postId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function PostPage({ params, searchParams }: PostPageProps) {
  const postId = parsePositiveId((await params).postId);
  if (postId === null) notFound();
  let detail;
  let rawSearchParams;
  try {
    [detail, rawSearchParams] = await Promise.all([getPost(postId), searchParams]);
  } catch (error) {
    if (error instanceof ApiError && error.code === "POST_NOT_FOUND") notFound();
    throw error;
  }
  return <PostDetail detail={detail} returnTo={safePostsReturnTo(rawSearchParams.return_to)} />;
}
