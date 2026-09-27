import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";

import { parseHistory, parseSessionList } from "./parsers";
import type { SessionHistory, SessionList } from "./types";

const BASE_PATH = "/api/v1/agent-sessions";

export function getSessions() {
  return serverApiRequest<SessionList>(`${BASE_PATH}?limit=20`, { parseData: parseSessionList });
}

export function getSessionHistory(sessionId: number) {
  return serverApiRequest<SessionHistory>(`${BASE_PATH}/${sessionId}?limit=20`, { parseData: parseHistory });
}
