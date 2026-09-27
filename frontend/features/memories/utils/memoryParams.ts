export type MemoryListParams = { query: string; campaignId: number | null; cursor: string };
type RawSearchParams = Record<string, string | string[] | undefined>;

export function parseMemoryListParams(raw: RawSearchParams): MemoryListParams {
  const rawQuery = typeof raw.query === "string" ? raw.query : "";
  const query = rawQuery.trim().slice(0, 1000);
  return {
    query,
    campaignId: parsePositiveId(raw.campaign_id),
    cursor: query || typeof raw.cursor !== "string" ? "" : raw.cursor.slice(0, 4096),
  };
}

export function memoryApiQuery(params: MemoryListParams): string {
  const query = new URLSearchParams({ limit: "20" });
  if (params.query) query.set("query", params.query);
  if (params.campaignId) query.set("campaign_id", String(params.campaignId));
  if (params.cursor) query.set("cursor", params.cursor);
  return query.toString();
}

export function memoryPageHref(params: MemoryListParams, cursor?: string): string {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.campaignId) query.set("campaign_id", String(params.campaignId));
  if (cursor) query.set("cursor", cursor);
  const value = query.toString();
  return value ? `/memories?${value}` : "/memories";
}

function parsePositiveId(value: string | string[] | undefined): number | null {
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
