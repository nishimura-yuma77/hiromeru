export type Memory = {
  id: number;
  content: string;
  similarity: number | null;
  campaigns: MemoryCampaign[];
  campaigns_next_cursor: string | null;
  posts: Array<{ post_id: number; published_at: string }>;
  posts_next_cursor: string | null;
};

export type MemoryCampaign = { id: number; title: string; archived_at: string | null };
export type MemoryPost = { post_id: number; published_at: string };
export type MemoryCampaignListResponse = { campaigns: MemoryCampaign[]; next_cursor: string | null };
export type MemoryPostListResponse = { posts: MemoryPost[]; next_cursor: string | null };

export type MemoryListResponse = {
  memories: Memory[];
  next_cursor: string | null;
};

export type DeleteMemoryResponse = { memory_id: number; deleted: true };
