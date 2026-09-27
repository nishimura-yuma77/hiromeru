import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { AuthenticatedLayoutClient } from "@/app/(authenticated)/AuthenticatedLayoutClient";
import { getCurrentMarketer } from "@/features/auth/server/getCurrentMarketer";
import { ApiError } from "@/shared/api/ApiError";
import { safeRedirectPath } from "@/shared/lib/safeRedirectPath";

export const dynamic = "force-dynamic";

export default async function AuthenticatedLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  let email: string;
  try {
    const marketer = await getCurrentMarketer();
    email = marketer.email;
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "UNAUTHENTICATED") {
      throw error;
    }

    const requestHeaders = await headers();
    const nextPath = safeRedirectPath(requestHeaders.get("x-hiromeru-path") ?? undefined);
    redirect(`/login?${new URLSearchParams({ next: nextPath }).toString()}`);
  }

  return <AuthenticatedLayoutClient email={email}>{children}</AuthenticatedLayoutClient>;
}
