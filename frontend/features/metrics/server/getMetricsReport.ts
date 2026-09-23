import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import type { MetricsReportResponse } from "@/features/metrics/types/metrics";
import { metricsQuery, type MetricsParams } from "@/features/metrics/utils/metricsParams";

export function getMetricsReport(params: MetricsParams): Promise<MetricsReportResponse> {
  const query = metricsQuery(params);
  return serverApiRequest<MetricsReportResponse>(`/api/v1/metrics${query ? `?${query}` : ""}`);
}
