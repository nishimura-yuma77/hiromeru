import type { PostListParams } from "@/features/posts/utils/postParams";

export const postKeys = {
  lists: ["posts", "list"] as const,
  list: (params: PostListParams) => [...postKeys.lists, params] as const,
  detail: (id: number) => ["posts", "detail", id] as const,
};
