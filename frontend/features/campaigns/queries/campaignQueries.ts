"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { browserApiRequest } from "@/shared/api/browserApiClient";
import { getCampaign } from "@/features/campaigns/api/getCampaign";
import { listCampaignsBrowser } from "@/features/campaigns/api/listCampaignsBrowser";
import type { CampaignListResponse } from "@/features/campaigns/types/campaign";
import type { CampaignListParams } from "@/features/campaigns/utils/campaignParams";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import type { CampaignOption } from "@/features/campaigns/queries/campaignKeys";

export function useCampaignListQuery(params: CampaignListParams) {
  return useQuery({ queryKey: campaignKeys.list(params), queryFn: ({ signal }) => listCampaignsBrowser(params, signal), placeholderData: keepPreviousData });
}

export function useCampaignDetailQuery(id: number) {
  return useQuery({ queryKey: campaignKeys.detail(id), queryFn: ({ signal }) => getCampaign(id, signal) });
}

export function useCampaignLabelQuery(id: number | null, initial?: CampaignOption | null) {
  return useQuery({
    queryKey: campaignKeys.label(id ?? 0),
    queryFn: async ({ signal }) => {
      const response = await browserApiRequest<{ campaign: CampaignOption }>(`/api/v1/campaigns/${id}`, { signal });
      return response.campaign;
    },
    enabled: id !== null,
    initialData: initial?.id === id ? initial : undefined,
  });
}

export function useCampaignOptionsQuery({ query, archived = null, enabled = true }: { query: string; archived?: boolean | null; enabled?: boolean }) {
  const trimmed = query.trim();
  return useQuery<CampaignListResponse>({
    queryKey: campaignKeys.options(trimmed, archived),
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({ limit: "20" });
      if (trimmed) params.set("query", trimmed);
      if (archived !== null) params.set("archived", String(archived));
      return browserApiRequest<CampaignListResponse>(`/api/v1/campaigns?${params}`, { method: "GET", signal });
    },
    enabled,
  });
}
