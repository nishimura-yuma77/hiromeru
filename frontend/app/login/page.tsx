import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginContainer } from "@/features/auth/containers/LoginContainer";
import { getCurrentUser } from "@/features/auth/server/getCurrentUser";
import { ApiError } from "@/shared/api/ApiError";
import { safeRedirectPath } from "@/shared/lib/safeRedirectPath";

export const metadata: Metadata = {
  title: "ログイン | Hiromeru",
};

type LoginPageProps = {
  searchParams: Promise<{ next?: string | string[]; registered?: string | string[] }>;
};

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const { next, registered } = await searchParams;
  const nextPath = safeRedirectPath(next);
  let initialFormError: string | null = null;
  let isLoggedIn = false;

  try {
    await getCurrentUser();
    isLoggedIn = true;
  } catch (error) {
    if (error instanceof ApiError && error.code === "UNAUTHENTICATED") {
      // An unauthenticated response is the expected state for this page.
    } else {
      initialFormError = "ログイン状態を確認できませんでした。ページを再読み込みしてください";
    }
  }

  if (isLoggedIn) {
    redirect(nextPath);
  }

  return (
    <LoginContainer
      portal="marketer"
      nextPath={nextPath}
      initialFormError={initialFormError}
      notice={registered ? "登録が完了しました。設定したパスワードでログインしてください" : null}
    />
  );
}
