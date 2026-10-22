export type AuthenticatedUser = {
  userId: number;
  email: string;
  isAdmin: boolean;
};

export type LoginResult = {
  userId: number;
  email: string;
  csrfToken: string;
};

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null && !Array.isArray(input);
}

function isPositiveInteger(input: unknown): input is number {
  return typeof input === "number" && Number.isInteger(input) && input > 0;
}

export function parseAuthenticatedUser(input: unknown): AuthenticatedUser {
  if (
    !isRecord(input) ||
    !isPositiveInteger(input.user_id) ||
    typeof input.email !== "string" ||
    typeof input.is_admin !== "boolean"
  ) {
    throw new Error("Invalid user");
  }
  return { userId: input.user_id, email: input.email, isAdmin: input.is_admin };
}

export function parseLoginResult(input: unknown): LoginResult {
  if (
    !isRecord(input) ||
    !isPositiveInteger(input.user_id) ||
    typeof input.email !== "string" ||
    typeof input.csrf_token !== "string" ||
    input.csrf_token.length === 0
  ) {
    throw new Error("Invalid login result");
  }
  return { userId: input.user_id, email: input.email, csrfToken: input.csrf_token };
}
