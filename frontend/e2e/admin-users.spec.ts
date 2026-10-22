import { expect, test } from "@playwright/test";

import {
  apiAs,
  createActiveUser,
  invitationLinks,
  lastInvitationLink,
  loginAsAdmin,
  loginAsMarketer,
  newCompanyWithAdmin,
  PASSWORD,
  resetBackend,
  setupCompany,
  uniqueEmail,
  userRow,
} from "./support/backend";

// E2E_TEST_SPEC 8章 E2E-016～E2E-020（Issue #58）。

test.beforeEach(async ({ request }) => {
  await resetBackend(request);
});

test("E2E-016 初期登録した責任者が管理画面とマーケター向け画面へログインする", async ({ page, request, context }) => {
  const email = uniqueEmail("owner");
  const created = await setupCompany(request, { company: "E2E-016社", name: "責任者A", email: `  ${email.toUpperCase()} ` });
  expect(created.status).toBe(201);

  // Step 1: 小文字のメールアドレスで管理者ログイン。
  await loginAsAdmin(page, email);
  const me = await apiAs(page, "GET", "/api/v1/auth/me");
  expect(me.body.data).toMatchObject({ email, is_admin: true });

  // Step 2: 再ログインせずマーケター向け画面を開き、「管理画面へ」が表示される。
  await page.getByRole("link", { name: "チャット・施策へ" }).click();
  await page.waitForURL("**/chat**");
  const adminLink = page.getByRole("link", { name: "管理画面へ" }).first();
  await expect(adminLink).toBeVisible();

  // Step 3: 同じCookieのまま管理画面へ戻る。
  await adminLink.click();
  await page.waitForURL("**/admin/users**");
  await expect(userRow(page, email)).toContainText("責任者");

  // Step 4: ログアウト後、マーケター用ログインでは認証されない。
  await page.getByRole("button", { name: "ログアウト" }).click();
  await page.waitForURL("**/admin/login**");
  const names = (await context.cookies()).map((cookie) => cookie.name);
  expect(names).not.toContain("hiromeru_session");
  expect(names).not.toContain("hiromeru_login_portal");
  await page.goto("/login");
  await page.getByLabel("メールアドレス").fill(email);
  await page.getByLabel("パスワード", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page.getByText("メールアドレスまたはパスワードが正しくありません").first()).toBeVisible();
  await expect(page).toHaveURL(/\/login/);

  // Step 5: 大小文字・前後空白だけ異なるメールアドレスでは、別会社も含めて登録しない。
  const again = await setupCompany(request, { company: "E2E-016別社", name: "別責任者", email: ` ${email.toUpperCase()}  ` });
  expect(again.status).toBe(409);
});

test("E2E-017 マーケターユーザーを招待し、本人が登録・ログインする", async ({ page, request, browser }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-017");
  await loginAsAdmin(page, admin.email);
  const invitee = uniqueEmail("invitee");

  // Step 1: 一覧からマーケターユーザーを招待する。
  await page.getByRole("button", { name: "新規招待" }).click();
  const dialog = page.getByRole("dialog", { name: "ユーザーを招待" });
  await dialog.getByLabel("マーケターユーザー").check();
  await dialog.getByLabel("表示名").fill("招待マーケター");
  await dialog.getByLabel("メールアドレス").fill(invitee);
  const [created] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/api/v1/admin/users") && response.request().method() === "POST"),
    dialog.getByRole("button", { name: "招待メールを送信" }).click(),
  ]);
  expect(created.status()).toBe(201);
  const row = userRow(page, invitee);
  await expect(row).toContainText("招待中");
  await expect(row).toContainText("送信受付済み");
  await expect(row).toContainText("マーケターユーザー");

  // Step 2: リンクを開き、送信前に再読み込みしてもフォームを続けられる。検証APIは呼ばない。
  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();
  const acceptanceCalls: string[] = [];
  inviteePage.on("request", (request) => {
    if (request.url().includes("/api/v1/invitation-acceptances")) acceptanceCalls.push(request.method());
  });
  const link = await lastInvitationLink(request, invitee);
  await inviteePage.goto(link);
  await inviteePage.reload();
  await expect(inviteePage).toHaveURL(/token=/);
  await expect(inviteePage.getByLabel("新しいパスワード")).toBeVisible();
  expect(acceptanceCalls).toEqual([]);

  // Step 3: パスワードを設定すると、履歴を置き換えてログイン画面へ移動する。
  await inviteePage.getByLabel("新しいパスワード").fill(PASSWORD);
  await inviteePage.getByRole("button", { name: "パスワードを設定" }).click();
  await inviteePage.waitForURL("**/login?registered=1");
  await expect(inviteePage.getByText("登録が完了しました")).toBeVisible();
  await inviteePage.goBack();
  await expect(inviteePage).not.toHaveURL(/token=/);
  await inviteePage.goto(link);
  await inviteePage.getByLabel("新しいパスワード").fill(PASSWORD);
  await inviteePage.getByRole("button", { name: "パスワードを設定" }).click();
  await expect(inviteePage.getByText("この招待リンクは利用できません")).toBeVisible();

  // Step 4: マーケター用ログインでマーケター向け画面を使え、管理画面への導線はない。
  await loginAsMarketer(inviteePage, invitee);
  await expect(inviteePage.getByRole("link", { name: "管理画面へ" })).toHaveCount(0);
  const me = await apiAs(inviteePage, "GET", "/api/v1/auth/me");
  expect(me.body.data).toMatchObject({ email: invitee, is_admin: false });
  await inviteeContext.close();
});

test("E2E-018 管理ユーザーを招待し、本人が登録・管理画面を開く", async ({ page, request, browser }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-018");
  await loginAsAdmin(page, admin.email);
  const invitee = uniqueEmail("invited-admin");

  // Step 1: 種別を管理ユーザーとして招待する。
  await page.getByRole("button", { name: "新規招待" }).click();
  const dialog = page.getByRole("dialog", { name: "ユーザーを招待" });
  await dialog.getByLabel("管理ユーザー").check();
  await dialog.getByLabel("表示名").fill("招待管理者");
  await dialog.getByLabel("メールアドレス").fill(invitee);
  await dialog.getByRole("button", { name: "招待メールを送信" }).click();
  await expect(userRow(page, invitee)).toContainText("管理ユーザー");
  await expect(userRow(page, invitee)).toContainText("招待中");

  // Step 2: パスワードを設定し、案内された管理者ログインから入る。Cookieは登録時に発行しない。
  const inviteeContext = await browser.newContext();
  const inviteePage = await inviteeContext.newPage();
  await inviteePage.goto(await lastInvitationLink(request, invitee));
  await inviteePage.getByLabel("新しいパスワード").fill(PASSWORD);
  await inviteePage.getByRole("button", { name: "パスワードを設定" }).click();
  await inviteePage.waitForURL("**/admin/login?registered=1");
  expect((await inviteeContext.cookies()).map((cookie) => cookie.name)).not.toContain("hiromeru_session");
  await inviteePage.getByLabel("メールアドレス").fill(invitee);
  await inviteePage.getByLabel("パスワード", { exact: true }).fill(PASSWORD);
  await inviteePage.getByRole("button", { name: "ログイン" }).click();
  await inviteePage.waitForURL("**/admin/users**");

  // Step 3: 再ログインせずマーケター向け画面を使える。
  await inviteePage.getByRole("link", { name: "チャット・施策へ" }).click();
  await inviteePage.waitForURL("**/chat**");
  const sessions = await apiAs(inviteePage, "GET", "/api/v1/agent-sessions");
  expect(sessions.status).toBe(200);
  await inviteeContext.close();
});

test("E2E-019 自社ユーザーの一覧・ページ移動・表示名編集を行う", async ({ page, request }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-019");
  await loginAsAdmin(page, admin.email);
  const invited: string[] = [];
  for (let index = 0; index < 24; index += 1) {
    const email = uniqueEmail(`member${index}`);
    invited.push(email);
    expect((await apiAs(page, "POST", "/api/v1/admin/users", { user_type: "marketer", name: `メンバー${index}`, email })).status).toBe(201);
  }
  const suspendedTarget = await createActiveUser(page, request, { name: "停止予定", userType: "marketer", label: "suspended" });
  expect((await apiAs(page, "POST", `/api/v1/admin/users/${suspendedTarget.userId}/suspensions`)).status).toBe(200);

  // Step 1: 先頭20人と総件数・総ページ数を表示する。
  await page.goto("/admin/users?page=1");
  await expect(page.getByText("全26件（1 / 2ページ）")).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(20);
  await expect(userRow(page, suspendedTarget.email)).toContainText("利用停止中");

  // Step 2: ページネーションでURLと表示内容が同期する。
  const pagination = page.getByRole("navigation", { name: "ユーザー一覧のページ移動" });
  await pagination.getByRole("button", { name: "次へ" }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.locator("tbody tr")).toHaveCount(6);
  await expect(userRow(page, admin.email)).toContainText("責任者");
  await pagination.getByRole("button", { name: "前へ" }).click();
  await expect(page).toHaveURL(/page=1/);
  await pagination.getByRole("button", { name: "最後" }).click();
  await expect(page).toHaveURL(/page=2/);
  await pagination.getByRole("button", { name: "先頭" }).click();
  await expect(page).toHaveURL(/page=1/);
  await expect(page.locator("tbody tr")).toHaveCount(20);

  // Step 3: 招待中・停止中のユーザーは種別を読み取り専用にし、確認なしで表示名を更新する。
  for (const [email, newName] of [[invited[23], "招待中の新しい名前"], [suspendedTarget.email, "停止中の新しい名前"]] as const) {
    await userRow(page, email).getByRole("button", { name: /を操作する/ }).click();
    const operate = page.getByRole("dialog", { name: "ユーザーを編集" });
    await expect(operate.getByText("種別は変更できません")).toBeVisible();
    await operate.getByLabel("表示名").fill(newName);
    const [patched] = await Promise.all([
      page.waitForResponse((response) => response.request().method() === "PATCH"),
      operate.getByRole("button", { name: "保存" }).click(),
    ]);
    expect(patched.status()).toBe(200);
    await expect(page.getByRole("alertdialog")).toHaveCount(0);
    await expect(userRow(page, email)).toContainText(newName);
  }

  // 範囲外のpageは先頭ページへ戻す。
  await page.goto("/admin/users?page=99");
  await expect(page).toHaveURL(/page=1/);
});

test("E2E-020 利用中ユーザーを昇格・降格し、旧ログインと本人の会話履歴を確認する", async ({ page, request, browser }) => {
  const admin = await newCompanyWithAdmin(request, "E2E-020");
  await loginAsAdmin(page, admin.email);
  const marketer = await createActiveUser(page, request, { name: "マーケターA", userType: "marketer", label: "promote" });
  const admin2 = await createActiveUser(page, request, { name: "管理者A2", userType: "admin", label: "demote" });

  const marketerContext = await browser.newContext();
  const marketerPage = await marketerContext.newPage();
  await loginAsMarketer(marketerPage, marketer.email);
  const marketerSession = (await apiAs(marketerPage, "POST", "/api/v1/agent-sessions")).body.data as { session_id: number };
  const admin2Context = await browser.newContext();
  const admin2Page = await admin2Context.newPage();
  await loginAsAdmin(admin2Page, admin2.email);
  const admin2Session = (await apiAs(admin2Page, "POST", "/api/v1/agent-sessions")).body.data as { session_id: number };

  // Step 1: 表示名と種別を変えて確認を開き、一度キャンセルする。入力は残り、PATCHは送られない。
  await page.reload();
  const patches: string[] = [];
  page.on("request", (request) => { if (request.method() === "PATCH") patches.push(request.url()); });
  await userRow(page, marketer.email).getByRole("button", { name: /を操作する/ }).click();
  const operate = page.getByRole("dialog", { name: "ユーザーを編集" });
  await operate.getByLabel("表示名").fill("昇格したA");
  await operate.getByLabel("管理ユーザー").check();
  await operate.getByRole("button", { name: "保存" }).click();
  const confirm = page.getByRole("alertdialog", { name: "ユーザー種別を変更しますか？" });
  await expect(confirm).toContainText("「マーケターユーザー」から「管理ユーザー」");
  await expect(confirm).toContainText("再ログイン");
  await confirm.getByRole("button", { name: "キャンセル" }).click();
  await expect(operate.getByLabel("表示名")).toHaveValue("昇格したA");
  expect(patches).toEqual([]);

  // Step 2: 再度確認して確定する。1回のPATCHで表示名と種別を更新する。
  await operate.getByRole("button", { name: "保存" }).click();
  await confirm.getByRole("button", { name: "種別を変更する" }).click();
  await expect(page.getByText("ユーザー種別を変更しました")).toBeVisible();
  expect(patches).toHaveLength(1);
  await expect(userRow(page, marketer.email)).toContainText("管理ユーザー");
  await expect(userRow(page, marketer.email)).toContainText("昇格したA");

  // Step 3: 旧Cookieは使えず、管理者ログインから入り直すと本人の会話履歴を使える。
  await marketerPage.reload();
  await marketerPage.waitForURL("**/login?next=**");
  await marketerPage.getByRole("link", { name: "管理ユーザーの方はこちら" }).click();
  await marketerPage.waitForURL("**/admin/login");
  await marketerPage.getByLabel("メールアドレス").fill(marketer.email);
  await marketerPage.getByLabel("パスワード", { exact: true }).fill(PASSWORD);
  await marketerPage.getByRole("button", { name: "ログイン" }).click();
  await marketerPage.waitForURL("**/admin/users**");
  const promotedSessions = await apiAs(marketerPage, "GET", "/api/v1/agent-sessions");
  const promotedIds = (promotedSessions.body.data as { sessions: { session_id: number }[] }).sessions.map((session) => session.session_id);
  expect(promotedIds).toContain(marketerSession.session_id);
  expect(promotedIds).not.toContain(admin2Session.session_id);

  // Step 4: ADMIN_A2の種別だけをマーケターユーザーへ変更する。
  await userRow(page, admin2.email).getByRole("button", { name: /を操作する/ }).click();
  await operate.getByLabel("マーケターユーザー").check();
  await operate.getByRole("button", { name: "保存" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "種別を変更する" }).click();
  await expect(userRow(page, admin2.email)).toContainText("マーケターユーザー");
  await expect(userRow(page, admin2.email)).toContainText("管理者A2");
  expect(patches).toHaveLength(2);

  // Step 5: 旧Cookieは使えず、管理者ログインは拒否され、マーケター用ログインで本人の会話を開ける。
  await admin2Page.reload();
  await admin2Page.waitForURL("**/admin/login**");
  await admin2Page.getByLabel("メールアドレス").fill(admin2.email);
  await admin2Page.getByLabel("パスワード", { exact: true }).fill(PASSWORD);
  await admin2Page.getByRole("button", { name: "ログイン" }).click();
  await expect(admin2Page.getByText("メールアドレスまたはパスワードが正しくありません").first()).toBeVisible();
  await admin2Page.getByRole("link", { name: "マーケターユーザーの方はこちら" }).click();
  await admin2Page.waitForURL("**/login");
  await loginAsMarketer(admin2Page, admin2.email);
  const demotedSessions = await apiAs(admin2Page, "GET", "/api/v1/agent-sessions");
  expect((demotedSessions.body.data as { sessions: { session_id: number }[] }).sessions.map((session) => session.session_id)).toContain(admin2Session.session_id);
  expect((await apiAs(admin2Page, "GET", "/api/v1/admin/users?page=1")).status).toBe(403);

  // 種別変更ではメールを送らず、招待・送信履歴は招待時の1通のまま。
  expect(await invitationLinks(request, marketer.email)).toHaveLength(1);
  expect(await invitationLinks(request, admin2.email)).toHaveLength(1);
  await marketerContext.close();
  await admin2Context.close();
});
