import { browserApiRequest } from "@/shared/api/browserApiClient";
import { ApiError, parseApiResponse } from "@/shared/api/ApiError";

import { parseCsrfToken, parseHistory, parseSession, parseSessionList, parseTurn } from "./parsers";
import type {
  AgentSession,
  AgentTurn,
  CampaignProposal,
  SessionHistory,
  SessionList,
  SseEvent,
  XPostProposal,
} from "./types";

const BASE_PATH = "/api/v1/agent-sessions";

export function createSession(signal: AbortSignal) {
  return browserApiRequest<AgentSession>(BASE_PATH, { method: "POST", parseData: parseSession, signal });
}

export function listSessions(cursor: string | null, signal: AbortSignal) {
  const query = new URLSearchParams({ limit: "20" });
  if (cursor) query.set("cursor", cursor);
  return browserApiRequest<SessionList>(`${BASE_PATH}?${query}`, { parseData: parseSessionList, signal });
}

export function getHistory(sessionId: number, signal: AbortSignal, before?: number) {
  const query = new URLSearchParams({ limit: "20" });
  if (before !== undefined) query.set("before_turn_number", String(before));
  return browserApiRequest<SessionHistory>(`${BASE_PATH}/${sessionId}?${query}`, { parseData: parseHistory, signal });
}

export function getTurn(sessionId: number, turnId: number, signal: AbortSignal) {
  return browserApiRequest<AgentTurn>(`${BASE_PATH}/${sessionId}/turns/${turnId}`, { parseData: parseTurn, signal });
}

export type CampaignApprovalResult = { id: number; agent_turn_id: number; title: string };
export type XPostApprovalResult = { post_id: number; agent_turn_id: number; campaign_id: number; x_post_id: string };

export function approveCampaign(sessionId: number, proposal: CampaignProposal, idempotencyKey: string) {
  return browserApiRequest<CampaignApprovalResult>(`${BASE_PATH}/${sessionId}/campaigns`, {
    method: "POST",
    body: proposal.id === null ? {
      title: proposal.title,
      target_profile: proposal.target_profile,
      background: proposal.background,
      objective: proposal.objective,
      plan: proposal.plan,
    } : proposal,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

export function approveXPost(sessionId: number, proposal: XPostProposal, idempotencyKey: string) {
  return browserApiRequest<XPostApprovalResult>(`${BASE_PATH}/${sessionId}/x/posts`, {
    method: "POST",
    body: proposal,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}

function readCookie(name: string) {
  const prefix = `${encodeURIComponent(name)}=`;
  const entry = document.cookie.split("; ").find((part) => part.startsWith(prefix));
  return entry ? decodeURIComponent(entry.slice(prefix.length)) : null;
}

async function openTurnStream(sessionId: number, message: string, signal: AbortSignal, csrfToken: string | null) {
  const headers = new Headers({ Accept: "text/event-stream", "Content-Type": "application/json" });
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  return fetch(`${BASE_PATH}/${sessionId}/turns`, {
    method: "POST",
    body: JSON.stringify({ message }),
    credentials: "same-origin",
    headers,
    signal,
  });
}

async function turnStreamResponse(sessionId: number, message: string, signal: AbortSignal) {
  let response = await openTurnStream(sessionId, message, signal, readCookie("csrf_token"));
  if (response.status === 403) {
    try {
      await parseApiResponse(response, () => null);
    } catch (error) {
      if (!(error instanceof ApiError) || error.code !== "CSRF_VALIDATION_FAILED") throw error;
    }
    const token = await browserApiRequest("/api/v1/auth/csrf", {
      method: "POST",
      parseData: parseCsrfToken,
      retryCsrf: false,
      signal,
    });
    response = await openTurnStream(sessionId, message, signal, token);
  }
  if (!response.ok || !response.headers.get("content-type")?.startsWith("text/event-stream")) {
    await parseApiResponse(response, parseTurn);
    throw new Error("ストリームを開始できませんでした。");
  }
  return response;
}

function parseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];

  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }

  if (data.length === 0) return null;
  return { event, data: JSON.parse(data.join("\n")) as unknown };
}

export async function streamTurn(
  sessionId: number,
  message: string,
  signal: AbortSignal,
  onEvent: (event: SseEvent) => void,
) {
  const response = await turnStreamResponse(sessionId, message, signal);

  if (!response.body) {
    throw new Error("ストリームを開始できませんでした。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    buffer = buffer.replaceAll("\r\n", "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const parsed = parseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      if (parsed) onEvent(parsed);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }

  if (buffer.trim()) {
    const parsed = parseBlock(buffer);
    if (parsed) onEvent(parsed);
  }
}
