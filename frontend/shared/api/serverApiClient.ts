import "server-only";

import { cookies } from "next/headers";

import {
  type ApiDataParser,
  normalizeFetchError,
  parseApiResponse,
} from "@/shared/api/ApiError";

type ServerApiRequestOptions<T> = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: HeadersInit;
  parseData?: ApiDataParser<T>;
  signal?: AbortSignal;
};

function passThroughData<T>(input: unknown): T {
  return input as T;
}

export async function serverApiRequest<T>(
  path: `/api/${string}`,
  options: ServerApiRequestOptions<T> = {},
): Promise<T> {
  const apiUrl = process.env.FASTAPI_URL;
  if (!apiUrl) {
    throw new Error("FASTAPI_URL is not configured.");
  }

  const cookieStore = await cookies();
  const headers = new Headers(options.headers);
  const cookieHeader = cookieStore.toString();
  if (cookieHeader) {
    headers.set("Cookie", cookieHeader);
  }
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(`${apiUrl.replace(/\/$/, "")}${path}`, {
      method: options.method ?? "GET",
      body:
        options.body === undefined
          ? undefined
          : typeof options.body === "string"
            ? options.body
            : JSON.stringify(options.body),
      headers,
      cache: "no-store",
      signal: options.signal ?? AbortSignal.timeout(15_000),
    });
    return await parseApiResponse(response, options.parseData ?? passThroughData<T>);
  } catch (error) {
    throw normalizeFetchError(error);
  }
}
