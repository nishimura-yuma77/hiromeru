import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import {
  parseAuthenticatedMarketer,
  type AuthenticatedMarketer,
} from "@/features/auth/types/auth";

export function getCurrentMarketer(): Promise<AuthenticatedMarketer> {
  return serverApiRequest("/api/v1/auth/me", { parseData: parseAuthenticatedMarketer });
}
