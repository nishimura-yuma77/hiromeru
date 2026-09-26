import type { AgentSession, AgentTurn, ApiError, ApprovalState, SessionHistory, SessionList, TurnItem } from "./types";

function record(input: unknown): Record<string, unknown> {
  if (typeof input !== "object" || input === null || Array.isArray(input)) throw new Error("Invalid object");
  return input as Record<string, unknown>;
}

function string(input: unknown): string {
  if (typeof input !== "string") throw new Error("Invalid string");
  return input;
}

function number(input: unknown): number {
  if (typeof input !== "number" || !Number.isSafeInteger(input)) throw new Error("Invalid number");
  return input;
}

function nullableString(input: unknown): string | null {
  return input === null ? null : string(input);
}

function oneOf<T extends string>(input: unknown, values: readonly T[]): T {
  const value = string(input);
  if (!values.includes(value as T)) throw new Error("Invalid enum value");
  return value as T;
}

function parseError(input: unknown): ApiError {
  const value = record(input);
  const fieldErrors = value.field_errors;
  return {
    code: string(value.code),
    message: string(value.message),
    retryable: value.retryable === true,
    field_errors: Array.isArray(fieldErrors) ? fieldErrors.map((entry) => {
      const error = record(entry);
      return {
        field: error.field === null ? null : string(error.field),
        code: string(error.code),
        message: string(error.message),
      };
    }) : undefined,
  };
}

const operations = ["upsert_campaign", "publish_x_post"] as const;

function parseApprovalState(input: unknown): ApprovalState | null {
  if (input === null) return null;
  const value = record(input);
  return {
    operation: oneOf(value.operation, operations),
    status: oneOf(value.status, ["processing", "succeeded", "failed", "outcome_unknown"] as const),
    external_effect_started: value.external_effect_started === true ? true : value.external_effect_started === false ? false : (() => { throw new Error("Invalid boolean"); })(),
    external_succeeded: value.external_succeeded === true ? true : value.external_succeeded === false ? false : (() => { throw new Error("Invalid boolean"); })(),
    recovery: value.recovery === null ? null : oneOf(value.recovery, ["retry_same_key", "manual_reconciliation"] as const),
  };
}

export function parseSession(input: unknown): AgentSession {
  const value = record(input);
  return {
    session_id: number(value.session_id),
    title: value.title === null ? null : string(value.title),
    created_at: string(value.created_at),
    updated_at: string(value.updated_at),
  };
}

function parseItem(input: unknown): TurnItem {
  const value = record(input);
  const base = {
    item_id: number(value.item_id),
    item_number: number(value.item_number),
    created_at: string(value.created_at),
  };
  const type = string(value.type);
  const content = record(value.content);
  if (type === "user_message" || type === "assistant_message") {
    return { ...base, type, content: { text: string(content.text) } };
  }
  if (type === "campaign_proposal") {
    return { ...base, type, content: {
      id: content.id === null ? null : number(content.id),
      expected_updated_at: nullableString(content.expected_updated_at),
      title: string(content.title),
      target_profile: string(content.target_profile),
      background: string(content.background),
      objective: string(content.objective),
      plan: string(content.plan),
    } };
  }
  if (type === "x_post_proposal") {
    return { ...base, type, content: {
      campaign_id: number(content.campaign_id),
      body: string(content.body),
      landing_url: string(content.landing_url),
    } };
  }
  if (type === "approval_action") {
    return { ...base, type, content: {
      id: string(content.id),
      type: oneOf(content.type, operations),
      request: record(content.request),
    } };
  }
  if (type === "api_result") {
    return { ...base, type, content: {
      operation: oneOf(content.operation, operations),
      success: content.success === true ? true : content.success === false ? false : (() => { throw new Error("Invalid boolean"); })(),
      error: content.error === null ? null : parseError(content.error),
    } };
  }
  return { ...base, type: "unknown", original_type: type, content };
}

export function parseTurn(input: unknown): AgentTurn {
  const value = record(input);
  if (!Array.isArray(value.items) || !Array.isArray(value.security_notices)) throw new Error("Invalid turn");
  return {
    agent_turn_id: number(value.agent_turn_id),
    turn_number: number(value.turn_number),
    kind: oneOf(value.kind, ["chat", "approval"] as const),
    status: oneOf(value.status, ["pending", "running", "completed", "failed", "cancelled", "blocked"] as const),
    error: value.error === null ? null : parseError(value.error),
    approval_state: parseApprovalState(value.approval_state),
    started_at: value.started_at === null ? null : string(value.started_at),
    completed_at: value.completed_at === null ? null : string(value.completed_at),
    security_notices: value.security_notices.map((notice) => {
      const item = record(notice);
      return {
        event_type: string(item.event_type),
        enforcement: string(item.enforcement),
        detected_at: string(item.detected_at),
      };
    }),
    items: value.items.map(parseItem),
  };
}

export function parseSessionList(input: unknown): SessionList {
  const value = record(input);
  if (!Array.isArray(value.sessions)) throw new Error("Invalid sessions");
  return {
    sessions: value.sessions.map(parseSession),
    next_cursor: value.next_cursor === null ? null : string(value.next_cursor),
  };
}

export function parseHistory(input: unknown): SessionHistory {
  const value = record(input);
  if (!Array.isArray(value.turns) || typeof value.has_more !== "boolean") throw new Error("Invalid history");
  return {
    session: parseSession(value.session),
    turns: value.turns.map(parseTurn),
    has_more: value.has_more,
  };
}

export function parseCsrfToken(input: unknown): string {
  return string(record(input).csrf_token);
}
