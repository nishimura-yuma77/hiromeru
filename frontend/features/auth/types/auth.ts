export type AuthenticatedMarketer = {
  marketerId: number;
  email: string;
};

export type LoginResult = AuthenticatedMarketer & {
  csrfToken: string;
};

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null && !Array.isArray(input);
}

export function parseAuthenticatedMarketer(input: unknown): AuthenticatedMarketer {
  if (
    !isRecord(input) ||
    !Number.isInteger(input.marketer_id) ||
    typeof input.marketer_id !== "number" ||
    input.marketer_id <= 0 ||
    typeof input.email !== "string"
  ) {
    throw new Error("Invalid marketer");
  }
  return { marketerId: input.marketer_id, email: input.email };
}

export function parseLoginResult(input: unknown): LoginResult {
  const marketer = parseAuthenticatedMarketer(input);
  if (!isRecord(input) || typeof input.csrf_token !== "string" || input.csrf_token.length === 0) {
    throw new Error("Invalid login result");
  }
  return { ...marketer, csrfToken: input.csrf_token };
}
