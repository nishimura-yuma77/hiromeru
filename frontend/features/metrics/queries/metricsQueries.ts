"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { getMetricsReportBrowser } from "@/features/metrics/api/getMetricsReportBrowser";
import type { MetricsParams } from "@/features/metrics/utils/metricsParams";
import { metricsKeys } from "@/features/metrics/queries/metricsKeys";

export function useMetricsReportQuery(params: MetricsParams) {
  return useQuery({ queryKey: metricsKeys.report(params), queryFn: ({ signal }) => getMetricsReportBrowser(params, signal), placeholderData: keepPreviousData });
}
