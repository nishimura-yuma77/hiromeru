"use client";

import {
  ApiError,
  type ApiDataParser,
  normalizeFetchError,
  parseApiResponse,
} from "@/shared/api/ApiError";
import { safeRedirectPath } from "@/shared/lib/safeRedirectPath";

type BrowserApiRequestOptions<T> = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: HeadersInit;
  parseData?: ApiDataParser<T>;
  signal?: AbortSignal;
  retryCsrf?: boolean;
};

const MUTATION_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function passThroughData<T>(input: unknown): T {
  return input as T;
}

function readCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`;
  const cookie = document.cookie.split("; ").find((entry) => entry.startsWith(prefix));
  if (!cookie) {
    return null;
  }

  try {
    return decodeURIComponent(cookie.slice(prefix.length));
  } catch {
    return null;
  }
}

function parseCsrfData(input: unknown): string {
  if (typeof input !== "object" || input === null || !("csrf_token" in input)) {
    throw new Error("Invalid CSRF response");
  }
  const token = input.csrf_token;
  if (typeof token !== "string" || token.length === 0) {
    throw new Error("Invalid CSRF token");
  }
  return token;
}

export function redirectToLogin(error: ApiError, force = false): void {
  if (
    (!force && error.code !== "UNAUTHENTICATED") ||
    typeof window === "undefined" ||
    window.location.pathname === "/login"
  ) {
    return;
  }

  const currentPath = safeRedirectPath(
    `${window.location.pathname}${window.location.search}${window.location.hash}`,
  );
  const loginUrl = new URL("/login", window.location.origin);
  loginUrl.search = new URLSearchParams({ next: currentPath }).toString();
  window.location.assign(loginUrl);
}

async function executeRequest<T>(
  path: `/api/${string}`,
  options: BrowserApiRequestOptions<T>,
  csrfToken: string | null,
): Promise<T> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (MUTATION_METHODS.has(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const response = await fetch(path, {
    method,
    body:
      options.body === undefined
        ? undefined
        : typeof options.body === "string"
          ? options.body
          : JSON.stringify(options.body),
    headers,
    credentials: "same-origin",
    signal: options.signal ?? AbortSignal.timeout(15_000),
  });
  return parseApiResponse(response, options.parseData ?? passThroughData<T>);
}

export async function browserApiRequest<T>(
  path: `/api/${string}`,
  options: BrowserApiRequestOptions<T>,
): Promise<T> {
  const method = options.method ?? "GET";
  const isMutation = MUTATION_METHODS.has(method);

  try {
    return await executeRequest(path, options, isMutation ? readCookie("csrf_token") : null);
  } catch (error) {
    const apiError = normalizeFetchError(error);
    redirectToLogin(apiError);
    if (
      !isMutation ||
      options.retryCsrf === false ||
      apiError.code !== "CSRF_VALIDATION_FAILED"
    ) {
      throw apiError;
    }

    try {
      const csrfToken = await executeRequest(
        "/api/v1/auth/csrf",
        { method: "POST", parseData: parseCsrfData, retryCsrf: false },
        null,
      );
      return await executeRequest(path, { ...options, retryCsrf: false }, csrfToken);
    } catch (retryError) {
      const retryApiError = normalizeFetchError(retryError);
      redirectToLogin(retryApiError, retryApiError.code === "CSRF_VALIDATION_FAILED");
      throw retryApiError;
    }
  }
}
