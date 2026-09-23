import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import type { PostDetailResponse } from "@/features/posts/types/post";

export function getPost(postId: number): Promise<PostDetailResponse> {
  return serverApiRequest<PostDetailResponse>(`/api/v1/posts/${postId}`);
}
