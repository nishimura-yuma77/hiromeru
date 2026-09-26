export type ApiError = {
  code: string;
  message: string;
  retryable?: boolean;
  field_errors?: Array<{ field: string | null; code: string; message: string }>;
};

export type AgentSession = {
  session_id: number;
  title: string | null;
  created_at: string;
  updated_at: string;
};

export type SessionList = {
  sessions: AgentSession[];
  next_cursor: string | null;
};

export type SecurityNotice = {
  event_type: string;
  enforcement: string;
  detected_at: string;
};

type TurnItemBase = {
  item_id: number;
  item_number: number;
  created_at: string;
};

export type CampaignProposal = {
  id: number | null;
  expected_updated_at: string | null;
  title: string;
  target_profile: string;
  background: string;
  objective: string;
  plan: string;
};

export type XPostProposal = {
  campaign_id: number;
  body: string;
  landing_url: string;
};

export type ApprovalOperation = "upsert_campaign" | "publish_x_post";
export type ApprovalStatus = "processing" | "succeeded" | "failed" | "outcome_unknown";
export type ApprovalState = {
  operation: ApprovalOperation;
  status: ApprovalStatus;
  external_effect_started: boolean;
  external_succeeded: boolean;
  recovery: "retry_same_key" | "manual_reconciliation" | null;
};

export type ApprovalAction = {
  id: string;
  type: "upsert_campaign" | "publish_x_post";
  request: Record<string, unknown>;
};

export type TurnItem = TurnItemBase & (
  | { type: "user_message"; content: { text: string } }
  | { type: "assistant_message"; content: { text: string } }
  | { type: "campaign_proposal"; content: CampaignProposal }
  | { type: "x_post_proposal"; content: XPostProposal }
  | { type: "approval_action"; content: ApprovalAction }
  | { type: "api_result"; content: { operation: ApprovalOperation; success: boolean; error: ApiError | null } }
  | { type: "unknown"; original_type: string; content: Record<string, unknown> }
);

export type TurnStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "blocked";

export type AgentTurn = {
  agent_turn_id: number;
  turn_number: number;
  kind: "chat" | "approval";
  status: TurnStatus;
  error: ApiError | null;
  approval_state: ApprovalState | null;
  started_at: string | null;
  completed_at: string | null;
  security_notices: SecurityNotice[];
  items: TurnItem[];
};

export type SessionHistory = {
  session: AgentSession;
  turns: AgentTurn[];
  has_more: boolean;
};

export type Activity = {
  activity_id: string;
  name: string;
  status: "running" | "succeeded" | "failed" | "blocked";
};

export type SseEvent = { event: string; data: unknown };
