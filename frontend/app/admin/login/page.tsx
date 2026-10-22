import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { LoginContainer } from "@/features/auth/containers/LoginContainer";
import { getCurrentUser } from "@/features/auth/server/getCurrentUser";
import { ApiError } from "@/shared/api/ApiError";
import { safeRedirectPath } from "@/shared/lib/safeRedirectPath";

export const metadata: Metadata = {
  title: "管理ユーザーのログイン | Hiromeru",
};

type AdminLoginPageProps = {
  searchParams: Promise<{ next?: string | string[]; registered?: string | string[] }>;
};

export default async function AdminLoginPage({ searchParams }: AdminLoginPageProps) {
  const { next, registered } = await searchParams;
  const nextPath = safeRedirectPath(next, "/admin/users");
  let initialFormError: string | null = null;
  let isAdmin = false;

  try {
    // ログイン済みの管理ユーザーだけフォームを表示せずSC-11へ進む（SCREEN_DESIGN SC-10）。
    isAdmin = (await getCurrentUser()).isAdmin;
  } catch (error) {
    if (!(error instanceof ApiError) || error.code !== "UNAUTHENTICATED") {
      initialFormError = "ログイン状態を確認できませんでした。ページを再読み込みしてください";
    }
  }

  if (isAdmin) {
    redirect(nextPath);
  }

  return (
    <LoginContainer
      portal="admin"
      nextPath={nextPath}
      initialFormError={initialFormError}
      notice={registered ? "登録が完了しました。設定したパスワードでログインしてください" : null}
    />
  );
}
