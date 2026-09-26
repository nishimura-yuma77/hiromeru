"use client";

import { useEffect, useReducer, useRef } from "react";
import { useRouter } from "next/navigation";

import { ApiError } from "@/shared/api/ApiError";

import { createSession, getHistory, getTurn, streamTurn } from "./api";
import { chatReducer, initialChatState } from "./state";
import { parseTurn } from "./parsers";
import type { Activity, SessionHistory, SseEvent } from "./types";

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
  const [state, dispatch] = useReducer(chatReducer, initialHistory, initialChatState);
  const abortRef = useRef<AbortController | null>(null);
  const sessionIdRef = useRef(initialHistory?.session.session_id ?? null);
  const turnIdRef = useRef<number | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function pollTurn(sessionId: number, turnId: number, signal: AbortSignal) {
    const deadline = Date.now() + POLL_TIMEOUT_MS;
    while (!signal.aborted && Date.now() < deadline) {
      const turn = await getTurn(sessionId, turnId, signal);
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

  async function recover(sessionId: number, signal: AbortSignal) {
    dispatch({ type: "recovering" });
    if (turnIdRef.current !== null) {
      await pollTurn(sessionId, turnIdRef.current, signal);
      return;
    }

    const history = await getHistory(sessionId, signal);
    dispatch({ type: "history_replaced", history });
    const latest = history.turns.at(-1);
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
    if (state.sending) return;

    dispatch({ type: "send_started", message: source });
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    turnIdRef.current = null;
    let createdSessionId: number | null = null;

    try {
      let sessionId = sessionIdRef.current;
      if (sessionId === null) {
        const session = await createSession(controller.signal);
        sessionId = session.session_id;
        createdSessionId = sessionId;
        sessionIdRef.current = sessionId;
        dispatch({ type: "session_created", session });
      }

      let finished = false;
      await streamTurn(sessionId, message, controller.signal, (event) => {
        receiveEvent(event);
        if (event.event === "turn_finished") finished = true;
      });
      if (!finished && !controller.signal.aborted) await recover(sessionId, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && error.agentTurnId !== null) {
        turnIdRef.current = error.agentTurnId;
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
          await recover(sessionIdRef.current, controller.signal);
          return;
        } catch (recoveryError) {
          if (controller.signal.aborted) return;
          dispatch({ type: "failed", message: errorMessage(recoveryError) });
          return;
        }
      }
      dispatch({ type: "failed", message: errorMessage(error) });
    } finally {
      if (createdSessionId !== null) router.replace(`/chat/${createdSessionId}`);
    }
  }

  async function loadEarlier() {
    const sessionId = sessionIdRef.current;
    const first = state.turns[0];
    if (sessionId === null || !first || state.loadingHistory || state.sending) return;
    dispatch({ type: "history_loading" });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const history = await getHistory(sessionId, controller.signal, first.turn_number);
      dispatch({ type: "history_prepended", history });
    } catch (error) {
      if (!controller.signal.aborted) dispatch({ type: "failed", message: errorMessage(error) });
    }
  }

  async function refreshHistory() {
    const sessionId = sessionIdRef.current;
    if (sessionId === null) return;
    const history = await getHistory(sessionId, AbortSignal.timeout(15_000));
    dispatch({ type: "history_replaced", history });
    window.dispatchEvent(new Event("chat:sessions-changed"));
  }

  return { state, dispatch, send, loadEarlier, refreshHistory, maxLength: MAX_MESSAGE_LENGTH };
}
