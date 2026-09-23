import { browserApiRequest } from "@/shared/api/browserApiClient";
import { parseLoginResult, type LoginResult } from "@/features/auth/types/auth";

type LoginRequest = {
  email: string;
  password: string;
};

function parseNull(input: unknown): null {
  if (input !== null) {
    throw new Error("Invalid empty response");
  }
  return null;
}

export function login(request: LoginRequest): Promise<LoginResult> {
  return browserApiRequest("/api/v1/auth/login", {
    method: "POST",
    body: request,
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
