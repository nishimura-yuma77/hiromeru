import { browserApiRequest } from "@/shared/api/browserApiClient";
import type { PostListResponse } from "@/features/posts/types/post";
import { postApiQuery, type PostListParams } from "@/features/posts/utils/postParams";

export function listPostsBrowser(params: PostListParams, signal: AbortSignal) {
  return browserApiRequest<PostListResponse>(`/api/v1/posts?${postApiQuery(params)}`, { method: "GET", signal });
}
