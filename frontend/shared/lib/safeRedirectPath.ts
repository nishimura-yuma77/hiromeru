const DEFAULT_AUTHENTICATED_PATH = "/chat";

export function safeRedirectPath(candidate: string | string[] | undefined): string {
  const path = Array.isArray(candidate) ? candidate[0] : candidate;
  if (
    !path ||
    !path.startsWith("/") ||
    path.startsWith("//") ||
    path.includes("\\") ||
    /[\u0000-\u001f\u007f]/.test(path)
  ) {
    return DEFAULT_AUTHENTICATED_PATH;
  }

  try {
    const parsed = new URL(path, "https://hiromeru.invalid");
    if (parsed.origin !== "https://hiromeru.invalid" || parsed.pathname === "/login") {
      return DEFAULT_AUTHENTICATED_PATH;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return DEFAULT_AUTHENTICATED_PATH;
  }
}
