const DEFAULT_AUTHENTICATED_PATH = "/chat";
const LOGIN_PATHS = new Set(["/login", "/admin/login"]);

export function safeRedirectPath(
  candidate: string | string[] | undefined,
  fallback: string = DEFAULT_AUTHENTICATED_PATH,
): string {
  const path = Array.isArray(candidate) ? candidate[0] : candidate;
  if (
    !path ||
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(path)
  ) {
    return fallback;
  }

  try {
    const parsed = new URL(path, "https://hiromeru.invalid");
    if (
      parsed.origin !== "https://hiromeru.invalid" ||
      LOGIN_PATHS.has(parsed.pathname) ||
      parsed.pathname.startsWith("/invitations")
    ) {
      return fallback;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return fallback;
  }
}
