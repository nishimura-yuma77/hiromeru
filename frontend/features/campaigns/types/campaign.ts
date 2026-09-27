export type MetricsSummary = {
  post_count: number;
  completed_count: number;
  pending_count: number;
  failed_count: number;
  x_pv_count: number;
  landing_user_count: number;
  landing_rate: number | null;
};

export type PostMetrics = {
  status: "pending" | "completed" | "failed";
  scheduled_at: string | null;
  measured_at: string | null;
  x_pv_count: number | null;
  landing_user_count: number | null;
};

export type CampaignListItem = {
  id: number;
  title: string;
  objective: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  similarity: number | null;
  metrics_summary: MetricsSummary;
};

export type CampaignListResponse = {
  campaigns: CampaignListItem[];
  next_cursor: string | null;
};

export type Campaign = {
  id: number;
  title: string;
  target_profile: string;
  background: string;
  objective: string;
  plan: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
};

export type CampaignDetailResponse = {
  campaign: Campaign;
  metrics_summary: MetricsSummary;
  posts: Array<{
    post_id: number;
    body: string;
    published_at: string;
    metrics: PostMetrics;
  }>;
  has_more_posts: boolean;
  memories: Array<{ id: number; content: string }>;
  has_more_memories: boolean;
};

export type CampaignEditRequest = Pick<
  Campaign,
  "title" | "target_profile" | "background" | "objective" | "plan"
> & { expected_updated_at: string };

export type CampaignEditResponse = {
  id: number;
  title: string;
  updated_at: string;
};
