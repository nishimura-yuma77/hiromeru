"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { listPostsBrowser } from "@/features/posts/api/listPostsBrowser";
import type { PostDetailResponse } from "@/features/posts/types/post";
import type { PostListParams } from "@/features/posts/utils/postParams";
import { postKeys } from "@/features/posts/queries/postKeys";
import { browserApiRequest } from "@/shared/api/browserApiClient";

export function usePostListQuery(params: PostListParams) {
  return useQuery({ queryKey: postKeys.list(params), queryFn: ({ signal }) => listPostsBrowser(params, signal), placeholderData: keepPreviousData });
}

export function usePostDetailQuery(id: number) {
  return useQuery({ queryKey: postKeys.detail(id), queryFn: ({ signal }) => browserApiRequest<PostDetailResponse>(`/api/v1/posts/${id}`, { signal }) });
}
