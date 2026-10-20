"use client";

import type { ReactNode } from "react";

import { useLogoutController } from "@/features/auth/controllers/useLogoutController";
import { AdminShell } from "@/features/shell/components/AdminShell/AdminShell";
import { QueryProvider } from "@/shared/components/QueryProvider/QueryProvider";

type AdminLayoutClientProps = {
  email: string;
  children: ReactNode;
};

export function AdminLayoutClient({ email, children }: AdminLayoutClientProps) {
  return <QueryProvider><AdminConsole email={email}>{children}</AdminConsole></QueryProvider>;
}

function AdminConsole({ email, children }: AdminLayoutClientProps) {
  // 管理画面からのログアウトはSC-10へ戻る（SCREEN_DESIGN 4章）。
  const logout = useLogoutController("/admin/login");
  return (
    <AdminShell email={email} logoutLoading={logout.isPending} logoutError={logout.error} onLogout={logout.onLogout}>
      {children}
    </AdminShell>
  );
}
