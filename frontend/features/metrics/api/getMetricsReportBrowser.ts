import { browserApiRequest } from "@/shared/api/browserApiClient";
import type { MetricsReportResponse } from "@/features/metrics/types/metrics";
import { metricsQuery, type MetricsParams } from "@/features/metrics/utils/metricsParams";

export function getMetricsReportBrowser(params: MetricsParams, signal: AbortSignal) {
  return browserApiRequest<MetricsReportResponse>(`/api/v1/metrics?${metricsQuery(params)}`, { method: "GET", signal });
}
