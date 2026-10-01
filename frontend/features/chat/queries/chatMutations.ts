"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { approveCampaign, approveXPost, createSession } from "@/features/chat/api";
import { sessionKeys } from "@/features/chat/queries/sessionKeys";
import type { CampaignProposal, XPostProposal } from "@/features/chat/types";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import { postKeys } from "@/features/posts/queries/postKeys";
import { metricsKeys } from "@/features/metrics/queries/metricsKeys";
import { memoryKeys } from "@/features/memories/queries/memoryKeys";

export function useCreateSessionMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (signal: AbortSignal) => createSession(signal),
    onSuccess: () => { void client.invalidateQueries({ queryKey: sessionKeys.list() }); },
  });
}

export function useApproveCampaignMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, proposal, idempotencyKey }: { sessionId: number; proposal: CampaignProposal; idempotencyKey: string }) =>
      approveCampaign(sessionId, proposal, idempotencyKey),
    onSuccess: (result, { sessionId }) => {
      void client.invalidateQueries({ queryKey: sessionKeys.list() });
      void client.invalidateQueries({ queryKey: sessionKeys.history(sessionId) });
      void client.invalidateQueries({ queryKey: campaignKeys.lists });
      void client.invalidateQueries({ queryKey: campaignKeys.optionLists });
      void client.invalidateQueries({ queryKey: campaignKeys.detail(result.id) });
      void client.invalidateQueries({ queryKey: campaignKeys.label(result.id) });
      void client.invalidateQueries({ queryKey: postKeys.lists });
      void client.invalidateQueries({ queryKey: metricsKeys.reports });
      void client.invalidateQueries({ queryKey: memoryKeys.all });
    },
  });
}

export function useApprovePostMutation() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, proposal, idempotencyKey }: { sessionId: number; proposal: XPostProposal; idempotencyKey: string }) =>
      approveXPost(sessionId, proposal, idempotencyKey),
    onSuccess: (result, { sessionId }) => {
      void client.invalidateQueries({ queryKey: sessionKeys.list() });
      void client.invalidateQueries({ queryKey: sessionKeys.history(sessionId) });
      void client.invalidateQueries({ queryKey: postKeys.lists });
      void client.invalidateQueries({ queryKey: postKeys.detail(result.post_id) });
      void client.invalidateQueries({ queryKey: campaignKeys.detail(result.campaign_id) });
      void client.invalidateQueries({ queryKey: metricsKeys.reports });
      void client.invalidateQueries({ queryKey: memoryKeys.all });
    },
  });
}
