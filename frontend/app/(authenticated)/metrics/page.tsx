import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { MetricsReport } from "@/features/metrics/components/MetricsReport/MetricsReport";
import { metricsKeys } from "@/features/metrics/queries/metricsKeys";
import { getMetricsReport } from "@/features/metrics/server/getMetricsReport";
import { parseMetricsParams } from "@/features/metrics/utils/metricsParams";
import { makeQueryClient } from "@/shared/api/queryClient";

type MetricsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MetricsPage({ searchParams }: MetricsPageProps) {
  const params = parseMetricsParams(await searchParams);
  const report = await getMetricsReport(params);
  const client = makeQueryClient();
  client.setQueryData(metricsKeys.report(params), report);
  return <HydrationBoundary state={dehydrate(client)}><MetricsReport report={report} params={params} /></HydrationBoundary>;
}
