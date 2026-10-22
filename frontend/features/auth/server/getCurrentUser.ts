import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import { parseAuthenticatedUser, type AuthenticatedUser } from "@/features/auth/types/auth";

export function getCurrentUser(): Promise<AuthenticatedUser> {
  return serverApiRequest("/api/v1/auth/me", { parseData: parseAuthenticatedUser });
}
