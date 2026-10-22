export type UserType = "admin" | "marketer";
export type UserStatus = "invited" | "active" | "suspended";
export type EmailStatus = "pending" | "accepted" | "failed" | "outcome_unknown";

export type CompanyUser = {
  userId: number;
  name: string;
  email: string;
  userType: UserType;
  status: UserStatus;
  isResponsible: boolean;
  emailStatus: EmailStatus | null;
};

export type CompanyUserPage = {
  users: CompanyUser[];
  page: number;
  pageSize: number;
  totalCount: number;
  totalPages: number;
};

const USER_TYPES: readonly string[] = ["admin", "marketer"];
const USER_STATUSES: readonly string[] = ["invited", "active", "suspended"];
const EMAIL_STATUSES: readonly string[] = ["pending", "accepted", "failed", "outcome_unknown"];

function isRecord(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null && !Array.isArray(input);
}

function isNonNegativeInteger(input: unknown): input is number {
  return typeof input === "number" && Number.isInteger(input) && input >= 0;
}

function isOneOf<T extends string>(input: unknown, values: readonly string[]): input is T {
  return typeof input === "string" && values.includes(input);
}

export function parseCompanyUser(input: unknown): CompanyUser {
  if (
    !isRecord(input) ||
    !isNonNegativeInteger(input.user_id) ||
    input.user_id === 0 ||
    typeof input.name !== "string" ||
    typeof input.email !== "string" ||
    !isOneOf<UserType>(input.user_type, USER_TYPES) ||
    !isOneOf<UserStatus>(input.status, USER_STATUSES) ||
    typeof input.is_responsible !== "boolean" ||
    !(input.email_status === null || isOneOf<EmailStatus>(input.email_status, EMAIL_STATUSES))
  ) {
    throw new Error("Invalid company user");
  }
  return {
    userId: input.user_id,
    name: input.name,
    email: input.email,
    userType: input.user_type,
    status: input.status,
    isResponsible: input.is_responsible,
    emailStatus: input.email_status,
  };
}

export function parseCompanyUserPage(input: unknown): CompanyUserPage {
  if (
    !isRecord(input) ||
    !Array.isArray(input.users) ||
    !isNonNegativeInteger(input.page) ||
    !isNonNegativeInteger(input.page_size) ||
    !isNonNegativeInteger(input.total_count) ||
    !isNonNegativeInteger(input.total_pages)
  ) {
    throw new Error("Invalid company user page");
  }
  return {
    users: input.users.map(parseCompanyUser),
    page: input.page,
    pageSize: input.page_size,
    totalCount: input.total_count,
    totalPages: input.total_pages,
  };
}

export function parseUserEnvelope(input: unknown): CompanyUser {
  if (!isRecord(input)) {
    throw new Error("Invalid user response");
  }
  return parseCompanyUser(input.user);
}

export function parseEmailStatus(input: unknown): EmailStatus {
  if (!isRecord(input) || !isOneOf<EmailStatus>(input.email_status, EMAIL_STATUSES)) {
    throw new Error("Invalid email status response");
  }
  return input.email_status;
}

export function parseInvitedUser(input: unknown): { userId: number } {
  if (!isRecord(input) || !isNonNegativeInteger(input.user_id) || input.user_id === 0) {
    throw new Error("Invalid invited user response");
  }
  return { userId: input.user_id };
}

export function parsePageParam(value: string | string[] | undefined | null): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^[1-9][0-9]{0,8}$/.test(raw)) {
    return 1;
  }
  return Number(raw);
}
