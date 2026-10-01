"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { editCampaign } from "@/features/campaigns/api/editCampaign";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import { postKeys } from "@/features/posts/queries/postKeys";
import { metricsKeys } from "@/features/metrics/queries/metricsKeys";
import { memoryKeys } from "@/features/memories/queries/memoryKeys";
import type { CampaignDetailResponse, CampaignEditRequest } from "@/features/campaigns/types/campaign";

export function useEditCampaignMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ campaignId, request }: { campaignId: number; request: CampaignEditRequest }) => editCampaign(campaignId, request),
    onSuccess: (result, { campaignId, request }) => {
      client.setQueryData<CampaignDetailResponse>(campaignKeys.detail(campaignId), (current) => current ? {
        ...current,
        campaign: {
          ...current.campaign,
          title: request.title,
          target_profile: request.target_profile,
          background: request.background,
          objective: request.objective,
          plan: request.plan,
          updated_at: result.updated_at,
        },
      } : current);
      client.setQueryData(campaignKeys.label(campaignId), (current: { id: number; title: string; archived_at?: string | null } | undefined) =>
        current ? { ...current, title: request.title } : current);
      void client.invalidateQueries({ queryKey: campaignKeys.lists });
      void client.invalidateQueries({ queryKey: campaignKeys.optionLists });
      void client.invalidateQueries({ queryKey: campaignKeys.detail(campaignId) });
      void client.invalidateQueries({ queryKey: postKeys.lists });
      void client.invalidateQueries({ queryKey: metricsKeys.reports });
      void client.invalidateQueries({ queryKey: memoryKeys.all });
    },
  });
}
