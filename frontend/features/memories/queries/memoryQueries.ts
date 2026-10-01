"use client";

import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { listMemoriesBrowser } from "@/features/memories/api/listMemoriesBrowser";
import { listMemoryCampaigns, listMemoryPosts } from "@/features/memories/api/listMemoryRelations";
import type { Memory } from "@/features/memories/types/memory";
import type { MemoryListParams } from "@/features/memories/utils/memoryParams";
import { memoryKeys } from "@/features/memories/queries/memoryKeys";

export function useMemoryListQuery(params: MemoryListParams) {
  return useQuery({ queryKey: memoryKeys.list(params), queryFn: ({ signal }) => listMemoriesBrowser(params, signal), placeholderData: keepPreviousData });
}

export function useMemoryCampaignsInfiniteQuery(memory: Memory) {
  const first = { campaigns: memory.campaigns, next_cursor: memory.campaigns_next_cursor };
  return useInfiniteQuery({
    queryKey: memoryKeys.campaigns(memory.id),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => pageParam ? listMemoryCampaigns(memory.id, pageParam, signal) : Promise.resolve(first),
    getNextPageParam: (last) => last.next_cursor,
    initialData: { pages: [first], pageParams: [null] },
  });
}

export function useMemoryPostsInfiniteQuery(memory: Memory) {
  const first = { posts: memory.posts, next_cursor: memory.posts_next_cursor };
  return useInfiniteQuery({
    queryKey: memoryKeys.posts(memory.id),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => pageParam ? listMemoryPosts(memory.id, pageParam, signal) : Promise.resolve(first),
    getNextPageParam: (last) => last.next_cursor,
    initialData: { pages: [first], pageParams: [null] },
  });
}
