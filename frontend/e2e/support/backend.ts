import { randomBytes } from "node:crypto";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

// E2E専用API（backend/api/routers/e2e.py）。事前条件の準備・外部障害の注入・事後確認だけに使う。
const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

// テスト用パスワードはSourceへ平文で保存せず、Secretまたは実行ごとの生成値を使う（E2E_TEST_SPEC 6.1）。
export const PASSWORD = process.env.E2E_PASSWORD ?? `Aa1!${randomBytes(12).toString("base64url")}`;

export type SesOutcome = "ok" | "throttled" | "rejected" | "unknown" | "interrupted";

let sequence = 0;

export function uniqueEmail(label: string): string {
  sequence += 1;
  return `${label}-${Date.now()}-${sequence}-${randomBytes(3).toString("hex")}@example.com`;
}

export async function resetBackend(request: APIRequestContext): Promise<void> {
  expect((await request.post(`${API_URL}/api/e2e/reset`)).ok()).toBe(true);
}

export async function setupCompany(
  request: APIRequestContext,
  input: { company: string; name: string; email: string; password?: string },
): Promise<{ status: number; userId: number | null }> {
  const response = await request.post(`${API_URL}/api/e2e/companies`, {
    data: { ...input, password: input.password ?? PASSWORD },
  });
  const body = await response.json();
  return { status: response.status(), userId: body.data?.user_id ?? null };
}

export async function invitationLinks(request: APIRequestContext, email: string): Promise<string[]> {
  const response = await request.get(`${API_URL}/api/e2e/emails`, { params: { to: email } });
  expect(response.ok()).toBe(true);
  const body = await response.json();
  // リンクの基点はE2E環境のFrontendへ揃える。
  return body.data.messages.map((message: { link: string | null }) => {
    const url = new URL(message.link ?? "");
    return `${url.pathname}${url.search}`;
  });
}

export async function lastInvitationLink(request: APIRequestContext, email: string): Promise<string> {
  const links = await invitationLinks(request, email);
  expect(links.length).toBeGreaterThan(0);
  return links[links.length - 1];
}

export async function reserveSesOutcomes(request: APIRequestContext, outcomes: SesOutcome[]): Promise<void> {
  expect((await request.post(`${API_URL}/api/e2e/email-outcomes`, { data: { outcomes } })).ok()).toBe(true);
}

export async function advanceClock(request: APIRequestContext, seconds: number): Promise<void> {
  expect((await request.post(`${API_URL}/api/e2e/clock`, { data: { advance_seconds: seconds } })).ok()).toBe(true);
}

// Browserの認証Cookie・CSRF Tokenを使ってAPIを呼ぶ（画面操作後の認可の事後確認や事前条件の準備用）。
export async function apiAs(
  page: Page,
  method: "GET" | "POST" | "PATCH",
  path: string,
  data?: Record<string, unknown>,
): Promise<{ status: number; body: { data: unknown; error: { code: string } | null } }> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === "csrf_token")?.value ?? "";
  const response = await page.request.fetch(path, {
    method,
    data,
    headers: { Origin: BASE_URL, "X-CSRF-Token": csrf },
  });
  return { status: response.status(), body: await response.json() };
}

export async function loginAsAdmin(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/admin/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await page.waitForURL("**/admin/users**");
}

export async function loginAsMarketer(page: Page, email: string, password = PASSWORD): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード", { exact: true }).fill(password);
  await page.getByRole("button", { name: "ログイン" }).click();
  await page.waitForURL("**/chat**");
}

export async function newCompanyWithAdmin(
  request: APIRequestContext,
  label: string,
): Promise<{ email: string; userId: number }> {
  const email = uniqueEmail(`${label}-owner`);
  const result = await setupCompany(request, { company: `${label}社`, name: `${label}責任者`, email });
  expect(result.status).toBe(201);
  return { email, userId: result.userId ?? 0 };
}

// 管理ユーザーのBrowserで招待し、本人の登録（パスワード設定）までをAPIで済ませる事前条件。
export async function createActiveUser(
  adminPage: Page,
  request: APIRequestContext,
  input: { name: string; userType: "admin" | "marketer"; label: string },
): Promise<{ email: string; userId: number }> {
  const email = uniqueEmail(input.label);
  const invited = await apiAs(adminPage, "POST", "/api/v1/admin/users", {
    user_type: input.userType,
    name: input.name,
    email,
  });
  expect(invited.status).toBe(201);
  const link = await lastInvitationLink(request, email);
  const token = new URL(link, BASE_URL).searchParams.get("token");
  const accepted = await request.post(`${BASE_URL}/api/v1/invitation-acceptances`, {
    data: { token, password: PASSWORD },
    headers: { Origin: BASE_URL },
  });
  expect(accepted.status()).toBe(200);
  return { email, userId: (invited.body.data as { user_id: number }).user_id };
}

export function userRow(page: Page, email: string) {
  return page.getByRole("row").filter({ hasText: email });
}
