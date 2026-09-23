"use client";

import { useEffect, useReducer } from "react";
import { useRouter } from "next/navigation";

import { editCampaign } from "@/features/campaigns/api/editCampaign";
import {
  campaignFormReducer,
  initialCampaignFormState,
  isCampaignFormDirty,
  type CampaignField,
} from "@/features/campaigns/state/campaignFormReducer";
import type { Campaign } from "@/features/campaigns/types/campaign";

function errorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null && "code" in error) {
    if (error.code === "CAMPAIGN_CONFLICT") {
      return "他の操作で施策が更新されました。入力内容を控えたうえで、ページを再読み込みして最新内容を確認してください。";
    }
    if (error.code === "CAMPAIGN_ARCHIVED") {
      return "この施策はアーカイブされたため編集できません。";
    }
  }
  return "施策を保存できませんでした。入力内容を残したまま、もう一度お試しください。";
}

export function useCampaignFormController(campaign: Campaign) {
  const router = useRouter();
  const [state, dispatch] = useReducer(
    campaignFormReducer,
    campaign,
    initialCampaignFormState,
  );
  const isDirty = isCampaignFormDirty(state, campaign);
  const canSave =
    isDirty &&
    !state.isPending &&
    Object.values(state.form).every((value) => value.trim().length > 0);

  useEffect(() => {
    if (!isDirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [isDirty]);

  function changeField(field: CampaignField, value: string) {
    dispatch({ type: "fieldChanged", field, value });
  }

  function cancel() {
    if (isDirty && !window.confirm("入力した変更を破棄しますか？")) return;
    dispatch({ type: "editingCancelled", campaign });
  }

  async function save() {
    if (!canSave || !window.confirm("既存の施策内容を置き換えて保存しますか？")) return;
    dispatch({ type: "saveStarted" });
    try {
      await editCampaign(campaign.id, state.form);
      dispatch({ type: "saveSucceeded" });
      router.refresh();
    } catch (error: unknown) {
      dispatch({ type: "saveFailed", message: errorMessage(error) });
    }
  }

  return {
    state,
    isDirty,
    canSave,
    startEditing: () => dispatch({ type: "editingStarted" }),
    changeField,
    cancel,
    save,
  };
}
