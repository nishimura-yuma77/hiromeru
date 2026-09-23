export type CampaignListParams = {
  query: string;
  archived: "all" | "active" | "archived";
  createdFrom: string;
  createdTo: string;
  cursor: string;
};

type RawSearchParams = Record<string, string | string[] | undefined>;

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

function first(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : "";
}

function validDate(value: string): string {
  if (!DATE_PATTERN.test(value)) return "";
  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
    ? value
    : "";
}

export function parseCampaignListParams(raw: RawSearchParams): CampaignListParams {
  const query = first(raw.query).trim().slice(0, 1000);
  const createdFrom = validDate(first(raw.created_from));
  const createdTo = validDate(first(raw.created_to));
  const hasValidRange = !createdFrom || !createdTo || createdFrom <= createdTo;
  return {
    query,
    archived: first(raw.archived) === "active" || first(raw.archived) === "archived"
      ? first(raw.archived) as "active" | "archived"
      : "all",
    createdFrom: hasValidRange ? createdFrom : "",
    createdTo: hasValidRange ? createdTo : "",
    cursor: query ? "" : first(raw.cursor).slice(0, 4096),
  };
}

export function toJstBoundary(date: string, isEnd: boolean): string | null {
  if (!date) return null;
  const parsed = new Date(`${date}T00:00:00+09:00`);
  if (isEnd) parsed.setUTCDate(parsed.getUTCDate() + 1);
  return parsed.toISOString();
}

export function campaignQuery(params: CampaignListParams): string {
  const query = new URLSearchParams({ limit: "20" });
  if (params.query) query.set("query", params.query);
  if (params.archived !== "all") query.set("archived", String(params.archived === "archived"));
  const createdFrom = toJstBoundary(params.createdFrom, false);
  const createdTo = toJstBoundary(params.createdTo, true);
  if (createdFrom) query.set("created_from", createdFrom);
  if (createdTo) query.set("created_to", createdTo);
  if (params.cursor) query.set("cursor", params.cursor);
  return query.toString();
}

export function campaignPageHref(params: CampaignListParams, cursor?: string): string {
  const query = new URLSearchParams();
  if (params.query) query.set("query", params.query);
  if (params.archived !== "all") query.set("archived", params.archived);
  if (params.createdFrom) query.set("created_from", params.createdFrom);
  if (params.createdTo) query.set("created_to", params.createdTo);
  if (cursor) query.set("cursor", cursor);
  const value = query.toString();
  return value ? `/campaigns?${value}` : "/campaigns";
}

export function parsePositiveId(value: string): number | null {
  if (!/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
}
