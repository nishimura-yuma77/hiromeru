import { expect, test, type Page } from "@playwright/test";

import {
  advanceClock,
  apiAs,
  BASE_URL,
  createActiveUser,
  invitationLinks,
  lastInvitationLink,
  loginAsAdmin,
  loginAsMarketer,
  newCompanyWithAdmin,
  PASSWORD,
  reserveSesOutcomes,
  resetBackend,
  uniqueEmail,
  userRow,
} from "./support/backend";

// E2E_TEST_SPEC 9章 E2E-E08～E2E-E14（Issue #58）。

test.beforeEach(async ({ request }) => {
  await resetBackend(request);
});

async function openOperation(page: Page, email: string) {
  await userRow(page, email).getByRole("button", { name: /を操作する/ }).click();
  return page.getByRole("dialog", { name: "ユーザーを編集" });
}

async function confirmState(page: Page, email: string, action: string, confirmLabel: string) {
  const operate = await openOperation(page, email);
  await operate.getByRole("button", { name: action }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: confirmLabel }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
}

async function inviteFromUi(page: Page, email: string, name: string) {
  await page.getByRole("button", { name: "新規招待" }).click();
  const dialog = page.getByRole("dialog", { name: "ユーザーを招待" });
  await dialog.getByLabel("表示名").fill(name);
  await dialog.getByLabel("メールアドレス").fill(email);
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/api/v1/admin/users") && r.request().method() === "POST"),
    dialog.getByRole("button", { name: "招待メールを送信" }).click(),
  ]);
  return response;
}

async function acceptFromUi(page: Page, link: string) {
  await page.goto(link);
  await page.getByLabel("新しいパスワード").fill(PASSWORD);
  await page.getByRole("button", { name: "パスワードを設定" }).click();
}

test("E2E-E08 利用停止・再開で旧ログインとリンクを失効させる", async ({ page, request, browser }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-E08");
  await loginAsAdmin(page, admin.email);
  const marketer = await createActiveUser(page, request, { name: "停止対象", userType: "marketer", label: "suspend" });
  const admin2 = await createActiveUser(page, request, { name: "管理者A2", userType: "admin", label: "admin2" });
  const invitee = uniqueEmail("invitee");
  expect((await apiAs(page, "POST", "/api/v1/admin/users", { user_type: "marketer", name: "招待中", email: invitee })).status).toBe(201);
  const inviteeLink = await lastInvitationLink(request, invitee);

  const marketerContext = await browser.newContext();
  const marketerPage = await marketerContext.newPage();
  await loginAsMarketer(marketerPage, marketer.email);
  const session = (await apiAs(marketerPage, "POST", "/api/v1/agent-sessions")).body.data as { session_id: number };

  // Step 1: 操作モーダルから停止し、確認モーダルで確定する。
  await page.reload();
  await confirmState(page, marketer.email, "利用停止", "利用停止する");
  await expect(userRow(page, marketer.email)).toContainText("利用停止中");

  // Step 2: 停止前のCookieは使えない。
  await marketerPage.reload();
  await marketerPage.waitForURL("**/login?next=**");
  expect((await apiAs(marketerPage, "GET", "/api/v1/auth/me")).status).toBe(401);

  // Step 3: 再開すると招待中へ戻るが、旧パスワードではログインできない。
  await confirmState(page, marketer.email, "利用を再開", "再開して招待メールを送る");
  await expect(userRow(page, marketer.email)).toContainText("招待中");
  expect(await invitationLinks(request, marketer.email)).toHaveLength(2);
  const oldLogin = await request.post(`${BASE_URL}/api/v1/auth/login`, {
    data: { email: marketer.email, password: PASSWORD },
    headers: { Origin: BASE_URL },
  });
  expect(oldLogin.status()).toBe(401);

  // Step 4: 同じ再開Requestを再送しても状態とメール送信は変わらない。
  const again = await apiAs(page, "POST", `/api/v1/admin/users/${marketer.userId}/reactivations`);
  expect(again.status).toBe(200);
  expect(await invitationLinks(request, marketer.email)).toHaveLength(2);

  // Step 5: 新しいリンクから登録すると利用中になり、本人の会話履歴は保持される。
  await acceptFromUi(marketerPage, await lastInvitationLink(request, marketer.email));
  await marketerPage.waitForURL("**/login?registered=1");
  await loginAsMarketer(marketerPage, marketer.email);
  const sessions = await apiAs(marketerPage, "GET", "/api/v1/agent-sessions");
  expect((sessions.body.data as { sessions: { session_id: number }[] }).sessions.map((s) => s.session_id)).toContain(session.session_id);

  // Step 6: 招待中のユーザーを停止すると、旧リンクは同じエラーで拒否される。
  await page.reload();
  await confirmState(page, invitee, "利用停止", "利用停止する");
  await acceptFromUi(marketerPage, inviteeLink);
  await expect(marketerPage.getByText("この招待リンクは利用できません")).toBeVisible();

  // Step 7: 管理ユーザー本人と責任者は、画面でもAPIでも停止できない。
  const admin2Context = await browser.newContext();
  const admin2Page = await admin2Context.newPage();
  await loginAsAdmin(admin2Page, admin2.email);
  for (const email of [admin2.email, admin.email]) {
    const operate = await openOperation(admin2Page, email);
    await expect(operate.getByRole("button", { name: "利用停止" })).toHaveCount(0);
    await operate.getByRole("button", { name: "閉じる" }).click();
  }
  for (const userId of [admin2.userId, admin.userId]) {
    const forbidden = await apiAs(admin2Page, "POST", `/api/v1/admin/users/${userId}/suspensions`);
    expect(forbidden.status).toBe(409);
    expect(forbidden.body.error?.code).toBe("USER_SUSPENSION_FORBIDDEN");
  }
  await marketerContext.close();
  await admin2Context.close();
});

test("E2E-E09 招待リンクの期限切れ・再送・一度きりの使用を確認する", async ({ page, request, browser }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-E09");
  await loginAsAdmin(page, admin.email);
  const invitee = uniqueEmail("expiring");
  expect((await inviteFromUi(page, invitee, "期限切れ対象")).status()).toBe(201);
  const firstLink = await lastInvitationLink(request, invitee);
  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();

  // Step 1: 発行から1時間を過ぎたリンクでは登録できない。
  await advanceClock(request, 3600);
  await acceptFromUi(inviteePage, firstLink);
  await expect(inviteePage.getByText("この招待リンクは利用できません")).toBeVisible();

  // Step 2: 再送すると古いリンクを無効化し、新しいリンクを送る。
  await page.reload();
  await confirmState(page, invitee, "招待メールを再送", "再送する");
  await expect(page.getByText("招待メールを再送しました")).toBeVisible();
  await expect(userRow(page, invitee)).toContainText("送信受付済み");
  const links = await invitationLinks(request, invitee);
  expect(links).toHaveLength(2);

  // Step 3: 新しいリンクは一度だけ使える。
  await acceptFromUi(inviteePage, links[1]);
  await inviteePage.waitForURL("**/login?registered=1");
  await acceptFromUi(inviteePage, links[1]);
  await expect(inviteePage.getByText("この招待リンクは利用できません")).toBeVisible();
  await acceptFromUi(inviteePage, firstLink);
  await expect(inviteePage.getByText("この招待リンクは利用できません")).toBeVisible();

  // Step 4: 利用中になったユーザーへは再送できない。
  await page.reload();
  const operate = await openOperation(page, invitee);
  await expect(operate.getByRole("button", { name: "招待メールを再送" })).toHaveCount(0);
  const invitedId = Number(await userRow(page, invitee).locator("td").first().textContent());
  const conflict = await apiAs(page, "POST", `/api/v1/admin/users/${invitedId}/invitations`);
  expect(conflict.status).toBe(409);
  expect(conflict.body.error?.code).toBe("USER_STATE_CONFLICT");
  expect(await invitationLinks(request, invitee)).toHaveLength(2);
  await inviteeContext.close();
});

test("E2E-E10 管理権限・他社ユーザー・他人の会話履歴の境界を確認する", async ({ page, request, browser }) => {
  const adminA = await newCompanyWithAdmin(request, "E2E-E10A");
  const adminB = await newCompanyWithAdmin(request, "E2E-E10B");
  await loginAsAdmin(page, adminA.email);
  const marketer = await createActiveUser(page, request, { name: "マーケターA", userType: "marketer", label: "marketer" });

  // Step 1: マーケターユーザーは管理画面を表示できず、管理APIは403。
  const marketerContext = await browser.newContext();
  const marketerPage = await marketerContext.newPage();
  await loginAsMarketer(marketerPage, marketer.email);
  const session = (await apiAs(marketerPage, "POST", "/api/v1/agent-sessions")).body.data as { session_id: number };
  await marketerPage.goto("/admin/users");
  await marketerPage.waitForURL("**/admin/login**");
  await expect(marketerPage.getByText(adminA.email)).toHaveCount(0);
  const forbidden = await apiAs(marketerPage, "GET", "/api/v1/admin/users?page=1");
  expect(forbidden.status).toBe(403);
  expect(forbidden.body.error?.code).toBe("ADMIN_FORBIDDEN");

  // Step 2: 他社のユーザーと存在しないIDは同じ404。
  const other = await apiAs(page, "PATCH", `/api/v1/admin/users/${adminB.userId}`, { name: "変更" });
  const missing = await apiAs(page, "PATCH", "/api/v1/admin/users/999999999", { name: "変更" });
  expect(other.status).toBe(404);
  expect(other.body).toEqual(missing.body);
  expect(other.body.error?.code).toBe("ADMIN_USER_NOT_FOUND");

  // Step 3: 同じ会社の他人の会話は管理ユーザーでも閲覧できない。
  const peek = await apiAs(page, "GET", `/api/v1/agent-sessions/${session.session_id}`);
  expect(peek.status).toBe(404);
  expect(peek.body.error?.code).toBe("AGENT_SESSION_NOT_FOUND");

  // Step 4: 自社・他社のメールアドレスは正規化後に同じ409で拒否する。
  const ownConflict = await inviteFromUi(page, `  ${marketer.email.toUpperCase()} `, "重複");
  expect(ownConflict.status()).toBe(409);
  await expect(page.getByText("このメールアドレスでは招待できません")).toBeVisible();
  await page.getByRole("dialog", { name: "ユーザーを招待" }).getByRole("button", { name: "キャンセル" }).click();
  const otherConflict = await inviteFromUi(page, ` ${adminB.email.toUpperCase()}`, "重複");
  expect(otherConflict.status()).toBe(409);
  expect(await ownConflict.json()).toEqual(await otherConflict.json());
  await marketerContext.close();
});

test("E2E-E11 SESの明確な失敗とスロットリング再試行を区別する", async ({ page, request }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-E11");
  await loginAsAdmin(page, admin.email);

  // Step 1: スロットリング2回の後に受付成功する。同じリンクで3回呼び出す。
  await reserveSesOutcomes(request, ["throttled", "throttled", "ok"]);
  const first = uniqueEmail("throttled");
  expect((await inviteFromUi(page, first, "再試行対象")).status()).toBe(201);
  const firstLinks = await invitationLinks(request, first);
  expect(firstLinks).toHaveLength(3);
  expect(new Set(firstLinks).size).toBe(1);
  await expect(userRow(page, first)).toContainText("送信受付済み");

  // Step 2: 明確な失敗では502を表示し、ユーザーは招待中のまま残る。
  await reserveSesOutcomes(request, ["rejected"]);
  const second = uniqueEmail("rejected");
  expect((await inviteFromUi(page, second, "失敗対象")).status()).toBe(502);
  await expect(page.getByText("招待メールを送信できませんでした").first()).toBeVisible();
  await expect(userRow(page, second)).toContainText("招待中");
  await expect(userRow(page, second)).toContainText("送信失敗");
  expect(await invitationLinks(request, second)).toHaveLength(1);

  // Step 3: 受付成功に戻し、管理ユーザーが明示的に再送する。
  await reserveSesOutcomes(request, []);
  await confirmState(page, second, "招待メールを再送", "再送する");
  await expect(userRow(page, second)).toContainText("送信受付済み");
  const secondLinks = await invitationLinks(request, second);
  expect(secondLinks).toHaveLength(2);
  expect(secondLinks[0]).not.toBe(secondLinks[1]);
});

for (const outcome of ["unknown", "interrupted"] as const) {
  // 5xx・408・応答なしはSESクライアントで「結果不明」に分類する（backend/tests/unit/test_email_client.py）。
  test(`E2E-E12 SESの結果不明で自動再送せず、管理者が手動再送する（${outcome}）`, async ({ page, request, browser }) => {
    const admin = await newCompanyWithAdmin(request, `E2E-E12-${outcome}`);
    await loginAsAdmin(page, admin.email);

    // Step 1: 結果不明を表示し、自動再送しない。
    await reserveSesOutcomes(request, [outcome]);
    const invitee = uniqueEmail(`unknown-${outcome}`);
    const response = await inviteFromUi(page, invitee, "結果不明対象");
    expect(response.status()).toBe(outcome === "unknown" ? 504 : 500);
    await expect(page.getByText("確認できませんでした").first()).toBeVisible();
    expect(await invitationLinks(request, invitee)).toHaveLength(1);

    // Step 2: 一覧を開き直しても招待中のまま、送信失敗と区別して表示する。
    await page.reload();
    await expect(userRow(page, invitee)).toContainText("招待中");
    await expect(userRow(page, invitee)).toContainText("送信結果を確認できませんでした");
    await advanceClock(request, 600);
    await page.reload();
    await expect(userRow(page, invitee)).toContainText("送信結果を確認できませんでした");

    // Step 3: 手動再送で古いリンクを無効化し、新しいリンクを送る。
    const oldLink = await lastInvitationLink(request, invitee);
    await confirmState(page, invitee, "招待メールを再送", "再送する");
    await expect(userRow(page, invitee)).toContainText("送信受付済み");
    expect(await invitationLinks(request, invitee)).toHaveLength(2);
    const inviteeContext = await browser.newContext();
    const inviteePage = await inviteeContext.newPage();
    await acceptFromUi(inviteePage, oldLink);
    await expect(inviteePage.getByText("この招待リンクは利用できません")).toBeVisible();
    await inviteeContext.close();
  });
}

test("E2E-E13 管理ユーザーの認証切れ後に管理者ログインへ戻る", async ({ page, request, context }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-E13");
  await loginAsAdmin(page, admin.email);
  await page.getByRole("link", { name: "チャット・施策へ" }).click();
  await page.waitForURL("**/chat**");
  const marketer = await createActiveUser(page, request, { name: "マーケター", userType: "marketer", label: "hint" });

  // Step 1: 認証Cookieだけを期限切れにする。入口ヒントは残す。
  await context.clearCookies({ name: "hiromeru_session" });
  expect((await context.cookies()).find((cookie) => cookie.name === "hiromeru_login_portal")?.value).toBe("admin");

  // Step 2: マーケター向け画面を再読み込みすると、元のURLを保持して管理者ログインへ移動する。
  await page.goto("/campaigns");
  await page.waitForURL(/\/admin\/login\?next=%2Fcampaigns/);

  // Step 3: 再ログインすると元の画面へ戻り、ログアウトで3種のCookieを削除する。
  await page.getByLabel("メールアドレス").fill(admin.email);
  await page.getByLabel("パスワード", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "ログイン" }).click();
  await page.waitForURL("**/campaigns");
  await page.getByRole("button", { name: "ログアウト" }).first().click();
  await page.waitForURL("**/login");
  const names = (await context.cookies()).map((cookie) => cookie.name);
  for (const name of ["hiromeru_session", "csrf_token", "hiromeru_login_portal"]) {
    expect(names).not.toContain(name);
  }

  // 入口ヒントを書き換えても管理APIの認可は変わらない。
  await loginAsMarketer(page, marketer.email);
  await context.addCookies([{ name: "hiromeru_login_portal", value: "admin", url: BASE_URL }]);
  expect((await apiAs(page, "GET", "/api/v1/admin/users?page=1")).status).toBe(403);
});

test("E2E-E14 禁止対象の種別変更と同時編集の競合を拒否する", async ({ page, request, browser }) => {
  const adminA = await newCompanyWithAdmin(request, "E2E-E14A");
  const adminB = await newCompanyWithAdmin(request, "E2E-E14B");
  await loginAsAdmin(page, adminA.email);
  const admin2 = await createActiveUser(page, request, { name: "管理者A2", userType: "admin", label: "admin2" });
  const marketer = await createActiveUser(page, request, { name: "マーケターA", userType: "marketer", label: "marketer" });
  const marketer2 = await createActiveUser(page, request, { name: "マーケターA2", userType: "marketer", label: "marketer2" });
  const suspended = await createActiveUser(page, request, { name: "停止中", userType: "marketer", label: "suspended" });
  expect((await apiAs(page, "POST", `/api/v1/admin/users/${suspended.userId}/suspensions`)).status).toBe(200);
  const invitee = uniqueEmail("invited");
  const invited = await apiAs(page, "POST", "/api/v1/admin/users", { user_type: "marketer", name: "招待中", email: invitee });
  const invitedId = (invited.body.data as { user_id: number }).user_id;

  const admin2Context = await browser.newContext();
  const admin2Page = await admin2Context.newPage();
  await loginAsAdmin(admin2Page, admin2.email);

  // Step 1: 自分自身・責任者・招待中・停止中は種別が読み取り専用で、表示名は編集できる。
  for (const email of [admin2.email, adminA.email, invitee, suspended.email]) {
    const operate = await openOperation(admin2Page, email);
    await expect(operate.getByText("種別は変更できません")).toBeVisible();
    await expect(operate.getByLabel("表示名")).toBeEditable();
    await operate.getByRole("button", { name: "閉じる" }).click();
  }

  // Step 2: 自分自身と責任者の種別変更はAPIでも409。
  for (const userId of [admin2.userId, adminA.userId]) {
    const result = await apiAs(admin2Page, "PATCH", `/api/v1/admin/users/${userId}`, { user_type: "marketer", name: "変更" });
    expect(result.status).toBe(409);
    expect(result.body.error?.code).toBe("USER_ROLE_CHANGE_FORBIDDEN");
  }

  // Step 3: 招待中・停止中の種別変更は409で、表示名も更新しない。
  for (const userId of [invitedId, suspended.userId]) {
    const result = await apiAs(admin2Page, "PATCH", `/api/v1/admin/users/${userId}`, { user_type: "admin", name: "変更" });
    expect(result.status).toBe(409);
    expect(result.body.error?.code).toBe("USER_STATE_CONFLICT");
  }
  await admin2Page.reload();
  await expect(userRow(admin2Page, invitee)).toContainText("招待中");
  await expect(userRow(admin2Page, invitee)).not.toContainText("変更");

  // Step 4: 確認中に別の管理ユーザーが対象を停止すると、確定は409で部分更新しない。
  const operate = await openOperation(admin2Page, marketer.email);
  await operate.getByLabel("表示名").fill("競合した名前");
  await operate.getByLabel("管理ユーザー").check();
  await operate.getByRole("button", { name: "保存" }).click();
  await expect(admin2Page.getByRole("alertdialog")).toBeVisible();
  expect((await apiAs(page, "POST", `/api/v1/admin/users/${marketer.userId}/suspensions`)).status).toBe(200);
  const [conflict] = await Promise.all([
    admin2Page.waitForResponse((r) => r.request().method() === "PATCH"),
    admin2Page.getByRole("alertdialog").getByRole("button", { name: "種別を変更する" }).click(),
  ]);
  expect(conflict.status()).toBe(409);
  await expect(operate.getByText("ユーザーの状態が変わったため")).toBeVisible();
  await expect(operate.getByText("種別は変更できません")).toBeVisible();
  await operate.getByRole("button", { name: "閉じる" }).click();
  await expect(userRow(admin2Page, marketer.email)).toContainText("マーケターA");
  await expect(userRow(admin2Page, marketer.email)).toContainText("利用停止中");

  // Step 5: 種別が変わらなければ停止中でも表示名だけ更新できる。
  const sameType = await apiAs(admin2Page, "PATCH", `/api/v1/admin/users/${suspended.userId}`, { user_type: "marketer", name: "停止中の新名" });
  expect(sameType.status).toBe(200);
  expect(await invitationLinks(request, suspended.email)).toHaveLength(1);

  // Step 6: 他社・存在しないIDは同じ404、管理権限なしは403。
  const otherCompany = await apiAs(admin2Page, "PATCH", `/api/v1/admin/users/${adminB.userId}`, { user_type: "marketer" });
  const missing = await apiAs(admin2Page, "PATCH", "/api/v1/admin/users/999999999", { user_type: "marketer" });
  expect(otherCompany.status).toBe(404);
  expect(otherCompany.body).toEqual(missing.body);
  const adminBContext = await browser.newContext();
  const adminBPage = await adminBContext.newPage();
  await loginAsAdmin(adminBPage, adminB.email);
  const crossCompany = await apiAs(adminBPage, "PATCH", `/api/v1/admin/users/${marketer2.userId}`, { user_type: "admin" });
  expect(crossCompany.status).toBe(404);
  const marketer2Context = await browser.newContext();
  const marketer2Page = await marketer2Context.newPage();
  await loginAsMarketer(marketer2Page, marketer2.email);
  const noAdmin = await apiAs(marketer2Page, "PATCH", `/api/v1/admin/users/${marketer2.userId}`, { user_type: "admin" });
  expect(noAdmin.status).toBe(403);
  expect(noAdmin.body.error?.code).toBe("ADMIN_FORBIDDEN");
  await admin2Context.close();
  await adminBContext.close();
  await marketer2Context.close();
});
