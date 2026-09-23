import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import type { PostListResponse } from "@/features/posts/types/post";
import { postApiQuery, type PostListParams } from "@/features/posts/utils/postParams";

export function listPosts(params: PostListParams): Promise<PostListResponse> {
  return serverApiRequest<PostListResponse>(`/api/v1/posts?${postApiQuery(params)}`);
}
