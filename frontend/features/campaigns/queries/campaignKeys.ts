import type { CampaignListParams } from "@/features/campaigns/utils/campaignParams";

export type CampaignOption = { id: number; title: string; archived_at?: string | null };

export const campaignKeys = {
  lists: ["campaigns", "list"] as const,
  list: (params: CampaignListParams) => [...campaignKeys.lists, params] as const,
  details: ["campaigns", "detail"] as const,
  detail: (id: number) => [...campaignKeys.details, id] as const,
  label: (id: number) => ["campaigns", "label", id] as const,
  optionLists: ["campaigns", "options"] as const,
  options: (query: string, archived: boolean | null) => [...campaignKeys.optionLists, query, archived] as const,
};
