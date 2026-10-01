"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";

import { getHistory, getTurn, listSessions } from "@/features/chat/api";
import { sessionKeys } from "@/features/chat/queries/sessionKeys";
import type { SessionList } from "@/features/chat/types";

export function useSessionListInfiniteQuery(initial: SessionList) {
  return useInfiniteQuery({
    queryKey: sessionKeys.list(),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => listSessions(pageParam, signal),
    getNextPageParam: (last) => last.next_cursor,
    initialData: { pages: [initial], pageParams: [null] },
  });
}

export function sessionHistoryOptions(sessionId: number, before?: number) {
  return { queryKey: sessionKeys.history(sessionId, before), queryFn: ({ signal }: { signal: AbortSignal }) => getHistory(sessionId, signal, before) };
}

export function useSessionHistoryQuery(sessionId: number | null, enabled = true) {
  return useQuery({
    queryKey: sessionKeys.history(sessionId ?? 0),
    queryFn: ({ signal }) => getHistory(sessionId!, signal),
    enabled: enabled && sessionId !== null,
  });
}

export function useTurnQuery(sessionId: number | null, turnId: number | null, enabled = true) {
  return useQuery({
    queryKey: sessionKeys.turn(sessionId ?? 0, turnId ?? 0),
    queryFn: ({ signal }) => getTurn(sessionId!, turnId!, signal),
    enabled: enabled && sessionId !== null && turnId !== null,
  });
}
