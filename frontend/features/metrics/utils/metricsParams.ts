export type MetricsParams = { publishedFrom: string; publishedTo: string; cursor: string };
type RawSearchParams = Record<string, string | string[] | undefined>;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function parseDate(value: string | string[] | undefined): string {
  if (typeof value !== "string" || !DATE_PATTERN.test(value)) return "";
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
    ? value
    : "";
}

export function parseMetricsParams(raw: RawSearchParams): MetricsParams {
  const publishedFrom = parseDate(raw.published_from);
  const publishedTo = parseDate(raw.published_to);
  const hasValidRange = !publishedFrom || !publishedTo || publishedFrom <= publishedTo;
  return {
    publishedFrom: hasValidRange ? publishedFrom : "",
    publishedTo: hasValidRange ? publishedTo : "",
    cursor: typeof raw.cursor === "string" ? raw.cursor.slice(0, 4096) : "",
  };
}

function boundary(value: string, isEnd: boolean): string | null {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00+09:00`);
  if (isEnd) parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString();
}

export function metricsQuery(params: MetricsParams): string {
  const query = new URLSearchParams({ limit: "20" });
  const from = boundary(params.publishedFrom, false);
  const to = boundary(params.publishedTo, true);
  if (from) query.set("published_from", from);
  if (to) query.set("published_to", to);
  if (params.cursor) query.set("cursor", params.cursor);
  return query.toString();
}

export function metricsPageHref(params: MetricsParams, cursor?: string): string {
  const query = new URLSearchParams();
  if (params.publishedFrom) query.set("published_from", params.publishedFrom);
  if (params.publishedTo) query.set("published_to", params.publishedTo);
  if (cursor) query.set("cursor", cursor);
  const value = query.toString();
  return value ? `/metrics?${value}` : "/metrics";
}
