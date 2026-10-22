import { browserApiRequest } from "@/shared/api/browserApiClient";

export type InvitedUserType = "admin" | "marketer";

function parseAcceptance(input: unknown): InvitedUserType {
  if (
    typeof input !== "object" ||
    input === null ||
    !("user_type" in input) ||
    (input.user_type !== "admin" && input.user_type !== "marketer")
  ) {
    throw new Error("Invalid invitation acceptance");
  }
  return input.user_type;
}

// 招待トークンはURLではなくBodyで送る。未ログインのためCSRF Tokenの再発行は行わない。
export function acceptInvitation(token: string, password: string): Promise<InvitedUserType> {
  return browserApiRequest("/api/v1/invitation-acceptances", {
    method: "POST",
    body: { token, password },
    parseData: parseAcceptance,
    retryCsrf: false,
  });
}
