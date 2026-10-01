import type { MetricsParams } from "@/features/metrics/utils/metricsParams";

export const metricsKeys = {
  reports: ["metrics", "report"] as const,
  report: (params: MetricsParams) => [...metricsKeys.reports, params] as const,
};
