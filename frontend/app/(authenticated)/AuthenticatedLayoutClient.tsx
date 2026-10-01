"use client";

import type { ReactNode } from "react";

import { useLogoutController } from "@/features/auth/controllers/useLogoutController";
import { AppShellContainer } from "@/features/shell/containers/AppShellContainer";
import { QueryProvider } from "@/shared/components/QueryProvider/QueryProvider";

type AuthenticatedLayoutClientProps = {
  email: string;
  children: ReactNode;
};

export function AuthenticatedLayoutClient({ email, children }: AuthenticatedLayoutClientProps) {
  return <QueryProvider><AuthenticatedShell email={email}>{children}</AuthenticatedShell></QueryProvider>;
}

function AuthenticatedShell({ email, children }: AuthenticatedLayoutClientProps) {
  const logoutController = useLogoutController();
  return (
    <AppShellContainer
      email={email}
      logoutLoading={logoutController.isPending}
      logoutError={logoutController.error}
      onLogout={logoutController.onLogout}
    >
      {children}
    </AppShellContainer>
  );
}
