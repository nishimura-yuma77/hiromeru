import type { Campaign, CampaignEditRequest } from "@/features/campaigns/types/campaign";

export type CampaignField = keyof Pick<
  CampaignEditRequest,
  "title" | "target_profile" | "background" | "objective" | "plan"
>;

export type CampaignFormState = {
  isEditing: boolean;
  isPending: boolean;
  form: CampaignEditRequest;
  error: string | null;
  isSaved: boolean;
};

export type CampaignFormEvent =
  | { type: "editingStarted" }
  | { type: "editingCancelled"; campaign: Campaign }
  | { type: "fieldChanged"; field: CampaignField; value: string }
  | { type: "saveStarted" }
  | { type: "saveSucceeded" }
  | { type: "saveFailed"; message: string };

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
  return {
    isEditing: false,
    isPending: false,
    form: toCampaignForm(campaign),
    error: null,
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
    case "fieldChanged":
      return {
        ...state,
        form: { ...state.form, [event.field]: event.value },
        error: null,
        isSaved: false,
      };
    case "saveStarted":
      return { ...state, isPending: true, error: null };
    case "saveSucceeded":
      return { ...state, isEditing: false, isPending: false, isSaved: true };
    case "saveFailed":
      return { ...state, isPending: false, error: event.message };
  }
}

export function isCampaignFormDirty(state: CampaignFormState, campaign: Campaign): boolean {
  const original = toCampaignForm(campaign);
  return (Object.keys(original) as Array<keyof CampaignEditRequest>).some(
    (field) => state.form[field] !== original[field],
  );
}
