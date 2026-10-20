// ログイン入口ヒントCookie（SCREEN_DESIGN 6.2「再ログイン先の選択」）。
// 認証切れ時の再ログイン先を選ぶためだけに使い、認証・認可・会社判定には使わない。

export type LoginPortal = "marketer" | "admin";

export const LOGIN_PORTAL_COOKIE = "hiromeru_login_portal";

const MAX_AGE_SECONDS = 30 * 24 * 60 * 60;

export function loginPathForPortal(portal: string | null | undefined): "/login" | "/admin/login" {
  return portal === "admin" ? "/admin/login" : "/login";
}

export function rememberLoginPortal(portal: LoginPortal): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${LOGIN_PORTAL_COOKIE}=${portal}; Max-Age=${MAX_AGE_SECONDS}; Path=/; SameSite=Lax${secure}`;
}

export function forgetLoginPortal(): void {
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${LOGIN_PORTAL_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax${secure}`;
}
