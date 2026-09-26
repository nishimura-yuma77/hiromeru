export type PostSort = "published_at_desc" | "published_at_asc" | "x_pv_count_desc" | "x_pv_count_asc";

export type PostListParams = {
  query: string;
  campaignId: number | null;
  publishedFrom: string;
  publishedTo: string;
  sort: PostSort;
  cursor: string;
};

type RawSearchParams = Record<string, string | string[] | undefined>;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const SORTS = new Set<PostSort>([
  "published_at_desc",
  "published_at_asc",
  "x_pv_count_desc",
  "x_pv_count_asc",
]);

function first(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

function dateInput(value: string): string {
  if (!DATE_PATTERN.test(value)) return "";
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
    ? value
    : "";
}

export function parsePositiveId(value: string): number | null {
  if (!/^[1-9]\d*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

export function parsePostListParams(raw: RawSearchParams): PostListParams {
  const query = first(raw.query).trim().slice(0, 1000);
  const rawSort = first(raw.sort) as PostSort;
  const publishedFrom = dateInput(first(raw.published_from));
  const publishedTo = dateInput(first(raw.published_to));
  const hasValidRange = !publishedFrom || !publishedTo || publishedFrom <= publishedTo;
  return {
    query,
    campaignId: parsePositiveId(first(raw.campaign_id)),
    publishedFrom: hasValidRange ? publishedFrom : "",
    publishedTo: hasValidRange ? publishedTo : "",
    sort: query || !SORTS.has(rawSort) ? "published_at_desc" : rawSort,
    cursor: query ? "" : first(raw.cursor).slice(0, 4096),
  };
}

function boundary(value: string, isEnd: boolean): string | null {
  if (!value) return null;
  const parsed = new Date(`${value}T00:00:00+09:00`);
  if (isEnd) parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString();
}

function splitSort(sort: PostSort): ["published_at" | "x_pv_count", "asc" | "desc"] {
  const separator = sort.lastIndexOf("_");
  return [
    sort.slice(0, separator) as "published_at" | "x_pv_count",
    sort.slice(separator + 1) as "asc" | "desc",
  ];
}

export function postApiQuery(params: PostListParams): string {
  const query = new URLSearchParams({ limit: "20" });
  if (params.query) query.set("query", params.query);
  if (params.campaignId) query.set("campaign_id", String(params.campaignId));
  const from = boundary(params.publishedFrom, false);
  const to = boundary(params.publishedTo, true);
  if (from) query.set("published_from", from);
  if (to) query.set("published_to", to);
  if (!params.query) {
    const [sort, order] = splitSort(params.sort);
    query.set("sort", sort);
    query.set("order", order);
    if (params.cursor) query.set("cursor", params.cursor);
  }
  return query.toString();
}

export function postPageHref(params: PostListParams, cursor?: string): string {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.campaignId) query.set("campaign_id", String(params.campaignId));
  if (params.publishedFrom) query.set("published_from", params.publishedFrom);
  if (params.publishedTo) query.set("published_to", params.publishedTo);
  if (!params.query && params.sort !== "published_at_desc") query.set("sort", params.sort);
  if (cursor) query.set("cursor", cursor);
  const value = query.toString();
  return value ? `/posts?${value}` : "/posts";
}

export function safePostsReturnTo(value: string | string[] | undefined): string {
  if (typeof value !== "string" || !value.startsWith("/posts")) return "/posts";
  try {
    const url = new URL(value, "https://hiromeru.local");
    return url.origin === "https://hiromeru.local" && url.pathname === "/posts"
      ? `${url.pathname}${url.search}`
      : "/posts";
  } catch {
    return "/posts";
  }
}
