import { browserApiRequest } from "@/shared/api/browserApiClient";
import { parseLoginResult, type LoginResult } from "@/features/auth/types/auth";
import type { LoginPortal } from "@/shared/lib/loginPortal";

export type LoginRequest = {
  email: string;
  password: string;
  portal: LoginPortal;
};

function parseNull(input: unknown): null {
  if (input !== null) {
    throw new Error("Invalid empty response");
  }
  return null;
}

export function login({ portal, ...credentials }: LoginRequest): Promise<LoginResult> {
  return browserApiRequest(portal === "admin" ? "/api/v1/admin/auth/login" : "/api/v1/auth/login", {
    method: "POST",
    body: credentials,
    parseData: parseLoginResult,
    retryCsrf: false,
  });
}

export function logout(): Promise<null> {
  return browserApiRequest("/api/v1/auth/logout", {
    method: "POST",
    parseData: parseNull,
    retryCsrf: false,
  });
}
