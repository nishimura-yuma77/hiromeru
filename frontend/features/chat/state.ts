import type { Activity, AgentSession, AgentTurn, SessionHistory } from "./types";

export type ChatState = {
  session: AgentSession | null;
  turns: AgentTurn[];
  hasMore: boolean;
  draft: string;
  pendingMessage: string | null;
  activities: Activity[];
  sending: boolean;
  recovering: boolean;
  loadingHistory: boolean;
  composerError: string | null;
  requestError: string | null;
};

export type ChatAction =
  | { type: "draft"; value: string }
  | { type: "validation"; message: string | null }
  | { type: "send_started"; message: string }
  | { type: "session_created"; session: AgentSession }
  | { type: "activity_started"; activity: Activity }
  | { type: "activity_finished"; id: string; status: Activity["status"] }
  | { type: "recovering" }
  | { type: "turn_finished"; turn: AgentTurn }
  | { type: "history_replaced"; history: SessionHistory }
  | { type: "history_loading" }
  | { type: "history_prepended"; history: SessionHistory }
  | { type: "failed"; message: string }
  | { type: "clear_error" };

export function initialChatState(history: SessionHistory | null): ChatState {
  return {
    session: history?.session ?? null,
    turns: history?.turns ?? [],
    hasMore: history?.has_more ?? false,
    draft: "",
    pendingMessage: null,
    activities: [],
    sending: false,
    recovering: false,
    loadingHistory: false,
    composerError: null,
    requestError: null,
  };
}

function upsertTurn(turns: AgentTurn[], turn: AgentTurn) {
  return [...turns.filter((item) => item.agent_turn_id !== turn.agent_turn_id), turn].sort(
    (a, b) => a.turn_number - b.turn_number,
  );
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "draft":
      return { ...state, draft: action.value, composerError: null };
    case "validation":
      return { ...state, composerError: action.message };
    case "send_started":
      return {
        ...state,
        draft: state.draft === action.message ? "" : state.draft,
        pendingMessage: action.message,
        activities: [],
        sending: true,
        recovering: false,
        composerError: null,
        requestError: null,
      };
    case "session_created":
      return { ...state, session: action.session };
    case "activity_started":
      return { ...state, activities: [...state.activities, action.activity] };
    case "activity_finished":
      return {
        ...state,
        activities: state.activities.map((activity) =>
          activity.activity_id === action.id ? { ...activity, status: action.status } : activity,
        ),
      };
    case "recovering":
      return { ...state, recovering: true, activities: [] };
    case "turn_finished":
      return {
        ...state,
        turns: upsertTurn(state.turns, action.turn),
        pendingMessage: null,
        activities: [],
        sending: false,
        recovering: false,
        requestError: null,
      };
    case "history_replaced":
      return {
        ...state,
        session: action.history.session,
        turns: action.history.turns,
        hasMore: action.history.has_more,
        pendingMessage: null,
      };
    case "history_loading":
      return { ...state, loadingHistory: true, requestError: null };
    case "history_prepended": {
      const existing = new Set(state.turns.map((turn) => turn.agent_turn_id));
      return {
        ...state,
        turns: [
          ...action.history.turns.filter((turn) => !existing.has(turn.agent_turn_id)),
          ...state.turns,
        ],
        hasMore: action.history.has_more,
        loadingHistory: false,
      };
    }
    case "failed":
      return {
        ...state,
        pendingMessage: null,
        activities: [],
        sending: false,
        recovering: false,
        loadingHistory: false,
        requestError: action.message,
      };
    case "clear_error":
      return { ...state, requestError: null };
  }
}
