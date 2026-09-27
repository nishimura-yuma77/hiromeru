export type MetricsSummary = {
  post_count: number;
  completed_count: number;
  pending_count: number;
  failed_count: number;
  x_pv_count: number;
  landing_user_count: number;
  landing_rate: number | null;
};

export type CampaignMetrics = MetricsSummary & { id: number; title: string; archived_at: string | null };

export type MetricsReportResponse = {
  published_from: string | null;
  published_to: string | null;
  summary: MetricsSummary;
  campaigns: CampaignMetrics[];
  next_cursor: string | null;
};
