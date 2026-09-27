export type PostMetrics = {
  status: "pending" | "completed" | "failed";
  scheduled_at: string | null;
  measured_at: string | null;
  x_pv_count: number | null;
  landing_user_count: number | null;
};

export type PostListItem = {
  post_id: number;
  campaign_id: number;
  campaign_title: string;
  campaign_archived_at: string | null;
  body: string;
  x_post_id: string;
  published_at: string;
  similarity: number | null;
  metrics: PostMetrics;
};

export type PostListResponse = {
  posts: PostListItem[];
  next_cursor: string | null;
};

export type PostDetailResponse = {
  post: {
    post_id: number;
    body: string;
    x_post_id: string;
    published_at: string;
  };
  campaign: { id: number; title: string; archived_at: string | null };
  tracking: {
    landing_url: string;
    utm_source: string;
    utm_medium: string;
    utm_campaign: string;
    utm_content: string;
    tracked_url: string;
  };
  metrics: PostMetrics;
};
