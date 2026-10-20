import { browserApiRequest } from "@/shared/api/browserApiClient";
import {
  parseCompanyUserPage,
  parseEmailStatus,
  parseInvitedUser,
  parseUserEnvelope,
  type CompanyUser,
  type CompanyUserPage,
  type EmailStatus,
  type UserType,
} from "@/features/users/types/user";

export type InviteUserRequest = { userType: UserType; name: string; email: string };
export type UpdateUserRequest = { name?: string; userType?: UserType };

export function listUsersBrowser(page: number, signal?: AbortSignal): Promise<CompanyUserPage> {
  return browserApiRequest(`/api/v1/admin/users?page=${page}`, {
    parseData: parseCompanyUserPage,
    signal,
  });
}

export function inviteUser(request: InviteUserRequest): Promise<{ userId: number }> {
  return browserApiRequest("/api/v1/admin/users", {
    method: "POST",
    body: { user_type: request.userType, name: request.name, email: request.email },
    parseData: parseInvitedUser,
  });
}

export function updateUser(userId: number, request: UpdateUserRequest): Promise<CompanyUser> {
  return browserApiRequest(`/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    body: { name: request.name, user_type: request.userType },
    parseData: parseUserEnvelope,
  });
}

export function suspendUser(userId: number): Promise<CompanyUser> {
  return browserApiRequest(`/api/v1/admin/users/${userId}/suspensions`, {
    method: "POST",
    parseData: parseUserEnvelope,
  });
}

export function reactivateUser(userId: number): Promise<CompanyUser> {
  return browserApiRequest(`/api/v1/admin/users/${userId}/reactivations`, {
    method: "POST",
    parseData: parseUserEnvelope,
  });
}

export function resendInvitation(userId: number): Promise<EmailStatus> {
  return browserApiRequest(`/api/v1/admin/users/${userId}/invitations`, {
    method: "POST",
    parseData: parseEmailStatus,
  });
}
