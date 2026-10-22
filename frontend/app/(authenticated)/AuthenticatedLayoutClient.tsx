"use client";

import type { ReactNode } from "react";

import { useLogoutController } from "@/features/auth/controllers/useLogoutController";
import { AppShellContainer } from "@/features/shell/containers/AppShellContainer";
import { QueryProvider } from "@/shared/components/QueryProvider/QueryProvider";

type AuthenticatedLayoutClientProps = {
  email: string;
  isAdmin: boolean;
  children: ReactNode;
};

export function AuthenticatedLayoutClient({ email, isAdmin, children }: AuthenticatedLayoutClientProps) {
  return <QueryProvider><AuthenticatedShell email={email} isAdmin={isAdmin}>{children}</AuthenticatedShell></QueryProvider>;
}

function AuthenticatedShell({ email, isAdmin, children }: AuthenticatedLayoutClientProps) {
  const logoutController = useLogoutController();
  return (
    <AppShellContainer
      email={email}
      isAdmin={isAdmin}
      logoutLoading={logoutController.isPending}
      logoutError={logoutController.error}
      onLogout={logoutController.onLogout}
    >
      {children}
    </AppShellContainer>
  );
}
