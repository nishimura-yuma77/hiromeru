import { MetricsReport } from "@/features/metrics/components/MetricsReport/MetricsReport";
import { getMetricsReport } from "@/features/metrics/server/getMetricsReport";
import { parseMetricsParams } from "@/features/metrics/utils/metricsParams";

type MetricsPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MetricsPage({ searchParams }: MetricsPageProps) {
  const params = parseMetricsParams(await searchParams);
  const report = await getMetricsReport(params);
  return <MetricsReport report={report} params={params} />;
}
