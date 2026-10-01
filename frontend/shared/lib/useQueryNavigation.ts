"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQueryClient, type QueryKey } from "@tanstack/react-query";

import { ApiError } from "@/shared/api/ApiError";

export function useQueryNavigation<P>({ parse, href, key, fetch, withoutCursor, fallbackError }: {
  parse: (search: string) => P;
  href: (params: P) => string;
  key: (params: P) => QueryKey;
  fetch: (params: P, signal: AbortSignal) => Promise<unknown>;
  withoutCursor?: (params: P) => P | null;
  fallbackError: string;
}) {
  const searchParams = useSearchParams();
  const params = parse(searchParams.toString());
  const client = useQueryClient();
  const sequence = useRef(0);
  const previousKey = useRef<QueryKey | null>(null);
  const lastAttempt = useRef<P | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function apply(next: P, replace = false): Promise<boolean> {
    const request = ++sequence.current;
    if (previousKey.current) void client.cancelQueries({ queryKey: previousKey.current, exact: true });
    const nextKey = key(next);
    previousKey.current = nextKey;
    lastAttempt.current = next;
    setPending(true);
    setError("");

    try {
      await client.fetchQuery({ queryKey: nextKey, queryFn: ({ signal }) => fetch(next, signal), staleTime: 0 });
      if (request !== sequence.current) return false;
      window.history[replace ? "replaceState" : "pushState"](null, "", href(next));
      return true;
    } catch (cause) {
      if (request !== sequence.current) return false;
      const firstPage = cause instanceof ApiError && cause.code === "INVALID_ARGUMENT" ? withoutCursor?.(next) : null;
      if (firstPage) {
        try {
          await client.fetchQuery({ queryKey: key(firstPage), queryFn: ({ signal }) => fetch(firstPage, signal), staleTime: 0 });
          if (request !== sequence.current) return false;
          window.history.replaceState(null, "", href(firstPage));
          return true;
        } catch (retryError) {
          if (request === sequence.current) setError(retryError instanceof Error ? retryError.message : fallbackError);
        }
      } else {
        setError(cause instanceof Error ? cause.message : fallbackError);
      }
      return false;
    } finally {
      if (request === sequence.current) {
        previousKey.current = null;
        setPending(false);
      }
    }
  }

  return { params, pending, error, apply, retry: () => { if (lastAttempt.current) void apply(lastAttempt.current); } };
}

export function useInvalidCursorRecovery<P>(error: unknown, params: P, withoutCursor: (params: P) => P | null, apply: (params: P, replace?: boolean) => Promise<boolean>) {
  const previous = useRef("");
  useEffect(() => {
    if (!(error instanceof ApiError) || error.code !== "INVALID_ARGUMENT") {
      previous.current = "";
      return;
    }
    const firstPage = withoutCursor(params);
    if (!firstPage) {
      previous.current = "";
      return;
    }
    const signature = JSON.stringify(params);
    if (previous.current === signature) return;
    previous.current = signature;
    void apply(firstPage, true);
  }, [error, params, withoutCursor, apply]);
}
