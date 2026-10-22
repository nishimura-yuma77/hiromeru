import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";

import { AuthenticatedLayoutClient } from "@/app/(authenticated)/AuthenticatedLayoutClient";
import { getCurrentUser } from "@/features/auth/server/getCurrentUser";
import { ApiError } from "@/shared/api/ApiError";
import { LOGIN_PORTAL_COOKIE, loginPathForPortal } from "@/shared/lib/loginPortal";
import { safeRedirectPath } from "@/shared/lib/safeRedirectPath";

export const dynamic = "force-dynamic";

export default async function AuthenticatedLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  let email: string;
  let isAdmin: boolean;
  try {
    ({ email, isAdmin } = await getCurrentUser());
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "UNAUTHENTICATED") {
      throw error;
    }

    // 再ログイン先はフロントエンドが管理する入口ヒントで選ぶ（SCREEN_DESIGN 6.2）。
    const loginPath = loginPathForPortal((await cookies()).get(LOGIN_PORTAL_COOKIE)?.value);
    const requestHeaders = await headers();
    const nextPath = safeRedirectPath(requestHeaders.get("x-hiromeru-path") ?? undefined);
    redirect(`${loginPath}?${new URLSearchParams({ next: nextPath }).toString()}`);
  }

  return <AuthenticatedLayoutClient email={email} isAdmin={isAdmin}>{children}</AuthenticatedLayoutClient>;
}
