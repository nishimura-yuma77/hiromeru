"use client";

import { useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/shared/api/ApiError";
import { useQueryClient } from "@tanstack/react-query";

import { getHistory, getTurn, streamTurn } from "./api";
import { useCreateSessionMutation } from "./queries/chatMutations";
import { sessionHistoryOptions, useSessionHistoryQuery } from "./queries/sessionQueries";
import { sessionKeys } from "./queries/sessionKeys";
import { chatReducer, initialChatState } from "./state";
import { parseTurn } from "./parsers";
import type { Activity, ClarificationAnswer, SessionHistory, SseEvent, TurnRequest } from "./types";

const MAX_MESSAGE_LENGTH = 4000;
const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 360000;
const TERMINAL_STATUSES = new Set(["completed", "failed", "blocked", "cancelled"]);

function errorMessage(error: unknown) {
  if (error instanceof Error && error.message) return error.message;
  return "通信に失敗しました。もう一度お試しください。";
}

export function useChatController(initialHistory: SessionHistory | null) {
  const router = useRouter();
  const client = useQueryClient();
  const createMutation = useCreateSessionMutation();
  const [state, dispatch] = useReducer(chatReducer, initialHistory, initialChatState);
  const historyQuery = useSessionHistoryQuery(initialHistory?.session.session_id ?? null);
  const abortRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);
  const sessionIdRef = useRef(initialHistory?.session.session_id ?? null);
  const turnIdRef = useRef<number | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (historyQuery.data && historyQuery.data !== initialHistory && !state.sending) {
      dispatch({ type: "history_replaced", history: historyQuery.data });
    }
  }, [historyQuery.data, initialHistory, state.sending]);

  async function pollTurn(sessionId: number, turnId: number, signal: AbortSignal) {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    while (!signal.aborted && Date.now() < deadline) {
      const turn = await client.fetchQuery({
        queryKey: sessionKeys.turn(sessionId, turnId),
        queryFn: ({ signal: querySignal }) => getTurn(sessionId, turnId, AbortSignal.any([signal, querySignal])),
        staleTime: 0,
      });
      if (TERMINAL_STATUSES.has(turn.status)) {
        dispatch({ type: "turn_finished", turn });
        window.dispatchEvent(new Event("chat:sessions-changed"));
        return;
      }
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(resolve, POLL_INTERVAL_MS);
        signal.addEventListener("abort", () => {
          window.clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    }
    if (!signal.aborted) dispatch({ type: "failed", message: "結果を確認できません。会話を再読み込みしてください。" });
  }

  async function recover(sessionId: number, signal: AbortSignal, input: TurnRequest) {
    dispatch({ type: "recovering" });
    if (turnIdRef.current !== null) {
      await pollTurn(sessionId, turnIdRef.current, signal);
      return;
    }

    const history = await client.fetchQuery({
      queryKey: sessionKeys.history(sessionId),
      queryFn: ({ signal: querySignal }) => getHistory(sessionId, AbortSignal.any([signal, querySignal])),
      staleTime: 0,
    });
    dispatch({ type: "history_replaced", history });
    const latest = history.turns.at(-1);
    if (latest && "clarification_response" in input && latest.items.some((item) =>
      item.type === "user_message" && item.content.clarification_response?.question_turn_id === input.clarification_response.question_turn_id
    )) {
      if (TERMINAL_STATUSES.has(latest.status)) {
        dispatch({ type: "turn_finished", turn: latest });
        window.dispatchEvent(new Event("chat:sessions-changed"));
      } else {
        turnIdRef.current = latest.agent_turn_id;
        await pollTurn(sessionId, latest.agent_turn_id, signal);
      }
      return;
    }
    if (latest && !TERMINAL_STATUSES.has(latest.status)) {
      turnIdRef.current = latest.agent_turn_id;
      await pollTurn(sessionId, latest.agent_turn_id, signal);
    } else {
      dispatch({ type: "failed", message: "送信結果を確認しました。必要に応じてもう一度入力してください。" });
    }
  }

  function receiveEvent(event: SseEvent) {
    if (event.event === "turn_started" && typeof event.data === "object" && event.data !== null && "agent_turn_id" in event.data) {
      turnIdRef.current = Number(event.data.agent_turn_id);
      return;
    }
    if (event.event === "activity_started" && typeof event.data === "object" && event.data !== null) {
      const data = event.data as { activity_id?: unknown; name?: unknown };
      dispatch({
        type: "activity_started",
        activity: {
          activity_id: String(data.activity_id ?? ""),
          name: String(data.name ?? ""),
          status: "running",
        },
      });
      return;
    }
    if (event.event === "activity_finished" && typeof event.data === "object" && event.data !== null) {
      const data = event.data as { activity_id?: unknown; status?: unknown };
      if (typeof data.activity_id !== "string" || !(["succeeded", "failed", "blocked"] as const).includes(data.status as "succeeded" | "failed" | "blocked")) return;
      dispatch({
        type: "activity_finished",
        id: data.activity_id,
        status: data.status as Activity["status"],
      });
      return;
    }
    if (event.event === "turn_finished") {
      dispatch({ type: "turn_finished", turn: parseTurn(event.data) });
      window.dispatchEvent(new Event("chat:sessions-changed"));
    }
  }

  async function sendRequest(input: TurnRequest, preview: string, clearDraft: boolean) {
    if (state.sending || sendingRef.current) return;
    if ("clarification_response" in input && sessionIdRef.current === null) return;
    sendingRef.current = true;
    dispatch({ type: "send_started", message: preview, clearDraft });
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    turnIdRef.current = null;
    let createdSessionId: number | null = null;

    try {
      let sessionId = sessionIdRef.current;
      if (sessionId === null) {
        const session = await createMutation.mutateAsync(controller.signal);
        sessionId = session.session_id;
        createdSessionId = sessionId;
        sessionIdRef.current = sessionId;
        dispatch({ type: "session_created", session });
      }

      let finished = false;
      await streamTurn(sessionId, input, controller.signal, (event) => {
        receiveEvent(event);
        if (event.event === "turn_finished") finished = true;
      });
      if (!finished && !controller.signal.aborted) await recover(sessionId, controller.signal, input);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.agentTurnId !== null) {
        turnIdRef.current = error.agentTurnId;
      }
      if (error instanceof ApiError && error.code === "CLARIFICATION_ALREADY_ANSWERED" && "clarification_response" in input && sessionIdRef.current !== null) {
        try {
          const question = await client.fetchQuery({
            queryKey: sessionKeys.turn(sessionIdRef.current, input.clarification_response.question_turn_id),
            queryFn: ({ signal }) => getTurn(sessionIdRef.current!, input.clarification_response.question_turn_id, AbortSignal.any([signal, controller.signal])),
            staleTime: 0,
          });
          dispatch({ type: "question_refreshed", turn: question });
        } catch {
          // The original API error is still shown if the question cannot be refreshed.
        }
        dispatch({ type: "failed", message: error.message });
        return;
      }
      if (
        error instanceof ApiError &&
        turnIdRef.current === null &&
        error.code !== "TURN_IN_PROGRESS"
      ) {
        dispatch({ type: "failed", message: error.message });
        return;
      }
      if (sessionIdRef.current !== null) {
        try {
          await recover(sessionIdRef.current, controller.signal, input);
          return;
        } catch (recoveryError) {
          if (controller.signal.aborted) return;
          dispatch({ type: "failed", message: errorMessage(recoveryError) });
          return;
        }
      }
      dispatch({ type: "failed", message: errorMessage(error) });
    } finally {
      sendingRef.current = false;
      if (createdSessionId !== null) router.replace(`/chat/${createdSessionId}`);
    }
  }

  async function send(explicitMessage?: string) {
    const source = explicitMessage ?? state.draft;
    const message = source.trim();
    if (!message) {
      dispatch({ type: "validation", message: "メッセージを入力してください。" });
      return;
    }
    if (source.length > MAX_MESSAGE_LENGTH) {
      dispatch({ type: "validation", message: "メッセージは4,000文字以内で入力してください。" });
      return;
    }
    await sendRequest({ message }, source, true);
  }

  async function sendClarification(questionTurnId: number, questions: string[], answers: ClarificationAnswer[]) {
    const preview = questions.map((question, index) => `質問${index + 1}: ${question}\n回答${index + 1}: ${answers[index].answer}`).join("\n");
    await sendRequest({ clarification_response: { question_turn_id: questionTurnId, answers } }, preview, false);
  }

  async function loadEarlier() {
    const sessionId = sessionIdRef.current;
    const first = state.turns[0];
    if (sessionId === null || !first || state.loadingHistory || state.sending) return;
    dispatch({ type: "history_loading" });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const history = await client.fetchQuery({
        queryKey: sessionKeys.history(sessionId, first.turn_number),
        queryFn: ({ signal }) => getHistory(sessionId, AbortSignal.any([controller.signal, signal]), first.turn_number),
        staleTime: 0,
      });
      dispatch({ type: "history_prepended", history });
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: "failed", message: errorMessage(error) });
    }
  }

  async function refreshHistory() {
    const sessionId = sessionIdRef.current;
    if (sessionId === null) return;
    const history = await client.fetchQuery({ ...sessionHistoryOptions(sessionId), staleTime: 0 });
    dispatch({ type: "history_replaced", history });
    window.dispatchEvent(new Event("chat:sessions-changed"));
  }

  return { state, dispatch, send, sendClarification, loadEarlier, refreshHistory, maxLength: MAX_MESSAGE_LENGTH };
}
