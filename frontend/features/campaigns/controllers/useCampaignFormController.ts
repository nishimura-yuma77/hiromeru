"use client";

import { useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";

import { editCampaign } from "@/features/campaigns/api/editCampaign";
import { getCampaign } from "@/features/campaigns/api/getCampaign";
import {
  campaignFormReducer,
  initialCampaignFormState,
  isCampaignFormDirty,
  type CampaignField,
} from "@/features/campaigns/state/campaignFormReducer";
import type { Campaign } from "@/features/campaigns/types/campaign";

const campaignFields = new Set<CampaignField>([
  "title",
  "target_profile",
  "background",
  "objective",
  "plan",
]);

type FormFailure = {
  message: string;
  fieldErrors: Partial<Record<CampaignField, string>>;
  hasConflict: boolean;
  isArchived: boolean;
};

function formFailure(error: unknown): FormFailure {
  const fieldErrors: Partial<Record<CampaignField, string>> = {};
  if (typeof error === "object" && error !== null && "fieldErrors" in error && Array.isArray(error.fieldErrors)) {
    for (const fieldError of error.fieldErrors) {
      if (
        typeof fieldError === "object" &&
        fieldError !== null &&
        "field" in fieldError &&
        "message" in fieldError &&
        typeof fieldError.field === "string" &&
        campaignFields.has(fieldError.field as CampaignField) &&
        typeof fieldError.message === "string"
      ) {
        fieldErrors[fieldError.field as CampaignField] = fieldError.message;
      }
    }
  }

  if (typeof error === "object" && error !== null && "code" in error) {
    if (error.code === "CAMPAIGN_CONFLICT") {
      return {
        message: "この施策は別の操作で更新されています。現在の入力は保存されていません。最新内容を読み込んでから、変更をやり直してください。",
        fieldErrors,
        hasConflict: true,
        isArchived: false,
      };
    }
    if (error.code === "CAMPAIGN_ARCHIVED") {
      return { message: "この施策はアーカイブされたため編集できません。", fieldErrors, hasConflict: false, isArchived: true };
    }
  }
  return {
    message: Object.keys(fieldErrors).length > 0
      ? "入力内容を確認してください。"
      : "施策を保存できませんでした。入力内容を残したまま、もう一度お試しください。",
    fieldErrors,
    hasConflict: false,
    isArchived: false,
  };
}

export function useCampaignFormController(campaign: Campaign) {
  const router = useRouter();
  const suppressUnloadWarning = useRef(false);
  const [state, dispatch] = useReducer(
    campaignFormReducer,
    campaign,
    initialCampaignFormState,
  );
  const isDirty = state.isEditing && isCampaignFormDirty(state);
  const canSave =
    isDirty &&
    !state.isPending &&
    Object.values(state.form).every((value) => value.trim().length > 0);

  useEffect(() => {
    if (!isDirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!suppressUnloadWarning.current) event.preventDefault();
    };
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
      const updated = await editCampaign(campaign.id, state.form);
      dispatch({ type: "saveSucceeded", updatedAt: updated.updated_at });
      router.refresh();
    } catch (error: unknown) {
      const failure = formFailure(error);
      dispatch({ type: "saveFailed", ...failure });
      if (failure.hasConflict || failure.isArchived) {
        try {
          const latest = await getCampaign(campaign.id);
          dispatch({ type: "conflictLoaded", campaign: latest.campaign });
          if (latest.campaign.archived_at) router.refresh();
        } catch {
          // Keep the draft and the conflict notice when the latest value cannot be loaded.
        }
      }
      const firstInvalidField = Array.from(campaignFields).find((field) => failure.fieldErrors[field]);
      if (firstInvalidField) {
        requestAnimationFrame(() => {
          const field = Array.from(document.getElementsByName(firstInvalidField)).find(
            (element): element is HTMLInputElement | HTMLTextAreaElement =>
              element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement,
          );
          field?.focus();
        });
      }
    }
  }

  function applyLatest() {
    if (!state.conflictCampaign || !window.confirm("入力中の変更を破棄して、最新の施策内容をフォームへ反映しますか？")) return;
    dispatch({ type: "latestApplied", campaign: state.conflictCampaign });
  }

  function keepDraft() {
    if (!state.conflictCampaign) return;
    dispatch({ type: "draftRebased", campaign: state.conflictCampaign });
  }

  return {
    state,
    isDirty,
    canSave,
    startEditing: () => dispatch({ type: "editingStarted" }),
    changeField,
    cancel,
    save,
    toggleConflictComparison: () => dispatch({ type: "conflictComparisonToggled" }),
    applyLatest,
    keepDraft,
  };
}
