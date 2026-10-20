import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { AdminLayoutClient } from "@/app/admin/(console)/AdminLayoutClient";
import { getCurrentUser } from "@/features/auth/server/getCurrentUser";
import { ApiError } from "@/shared/api/ApiError";
import { safeRedirectPath } from "@/shared/lib/safeRedirectPath";

export const dynamic = "force-dynamic";

export default async function AdminLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  let email: string;
  let isAdmin: boolean;
  try {
    ({ email, isAdmin } = await getCurrentUser());
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "UNAUTHENTICATED") {
      throw error;
    }
    isAdmin = false;
    email = "";
  }

  if (!isAdmin) {
    // 管理画面での認証切れと、管理権限のないユーザーはSC-10へ移動する。
    const requestHeaders = await headers();
    const nextPath = safeRedirectPath(requestHeaders.get("x-hiromeru-path") ?? undefined, "/admin/users");
    redirect(`/admin/login?${new URLSearchParams({ next: nextPath }).toString()}`);
  }

  return <AdminLayoutClient email={email}>{children}</AdminLayoutClient>;
}
