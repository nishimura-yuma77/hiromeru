import "server-only";

import { serverApiRequest } from "@/shared/api/serverApiClient";
import { parseCompanyUserPage, type CompanyUserPage } from "@/features/users/types/user";

export function listUsers(page: number): Promise<CompanyUserPage> {
  return serverApiRequest(`/api/v1/admin/users?page=${page}`, { parseData: parseCompanyUserPage });
}
