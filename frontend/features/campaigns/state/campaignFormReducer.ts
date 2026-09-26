import type { Campaign, CampaignEditRequest } from "@/features/campaigns/types/campaign";

export type CampaignField = keyof Pick<
  CampaignEditRequest,
  "title" | "target_profile" | "background" | "objective" | "plan"
>;

export type CampaignFormState = {
  isEditing: boolean;
  isPending: boolean;
  form: CampaignEditRequest;
  baseline: CampaignEditRequest;
  error: string | null;
  fieldErrors: Partial<Record<CampaignField, string>>;
  hasConflict: boolean;
  conflictCampaign: Campaign | null;
  showConflictComparison: boolean;
  isSaved: boolean;
};

export type CampaignFormEvent =
  | { type: "editingStarted" }
  | { type: "editingCancelled"; campaign: Campaign }
  | { type: "fieldChanged"; field: CampaignField; value: string }
  | { type: "saveStarted" }
  | { type: "saveSucceeded"; updatedAt: string }
  | { type: "conflictLoaded"; campaign: Campaign }
  | { type: "conflictComparisonToggled" }
  | { type: "latestApplied"; campaign: Campaign }
  | { type: "draftRebased"; campaign: Campaign }
  | {
      type: "saveFailed";
      message: string;
      fieldErrors: Partial<Record<CampaignField, string>>;
      hasConflict: boolean;
    };

export function toCampaignForm(campaign: Campaign): CampaignEditRequest {
  return {
    title: campaign.title,
    target_profile: campaign.target_profile,
    background: campaign.background,
    objective: campaign.objective,
    plan: campaign.plan,
    expected_updated_at: campaign.updated_at,
  };
}

export function initialCampaignFormState(campaign: Campaign): CampaignFormState {
  const form = toCampaignForm(campaign);
  return {
    isEditing: false,
    isPending: false,
    form,
    baseline: form,
    error: null,
    fieldErrors: {},
    hasConflict: false,
    conflictCampaign: null,
    showConflictComparison: false,
    isSaved: false,
  };
}

export function campaignFormReducer(
  state: CampaignFormState,
  event: CampaignFormEvent,
): CampaignFormState {
  switch (event.type) {
    case "editingStarted":
      return { ...state, isEditing: true, isSaved: false };
    case "editingCancelled":
      return initialCampaignFormState(event.campaign);
    case "fieldChanged": {
      const remainingFieldErrors = { ...state.fieldErrors };
      delete remainingFieldErrors[event.field];
      return {
        ...state,
        form: { ...state.form, [event.field]: event.value },
        error: null,
        fieldErrors: remainingFieldErrors,
        hasConflict: false,
        conflictCampaign: null,
        showConflictComparison: false,
        isSaved: false,
      };
    }
    case "saveStarted":
      return { ...state, isPending: true, error: null, fieldErrors: {}, hasConflict: false, conflictCampaign: null, showConflictComparison: false };
    case "saveSucceeded":
      return {
        ...state,
        isEditing: false,
        isPending: false,
        form: { ...state.form, expected_updated_at: event.updatedAt },
        baseline: { ...state.form, expected_updated_at: event.updatedAt },
        isSaved: true,
      };
    case "conflictLoaded":
      return { ...state, conflictCampaign: event.campaign };
    case "conflictComparisonToggled":
      return { ...state, showConflictComparison: !state.showConflictComparison };
    case "latestApplied":
      return {
        ...state,
        form: toCampaignForm(event.campaign),
        baseline: toCampaignForm(event.campaign),
        error: null,
        hasConflict: false,
        conflictCampaign: null,
        showConflictComparison: false,
        isSaved: false,
      };
    case "draftRebased":
      return {
        ...state,
        form: { ...state.form, expected_updated_at: event.campaign.updated_at },
        baseline: toCampaignForm(event.campaign),
        error: null,
        hasConflict: false,
        conflictCampaign: null,
        showConflictComparison: false,
      };
    case "saveFailed":
      return {
        ...state,
        isPending: false,
        error: event.message,
        fieldErrors: event.fieldErrors,
        hasConflict: event.hasConflict,
      };
  }
}

export function isCampaignFormDirty(state: CampaignFormState): boolean {
  return (Object.keys(state.baseline) as Array<keyof CampaignEditRequest>).some(
    (field) => state.form[field] !== state.baseline[field],
  );
}
