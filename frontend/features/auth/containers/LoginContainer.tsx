"use client";

import { LoginView } from "@/features/auth/components/LoginView/LoginView";
import { useLoginController } from "@/features/auth/controllers/useLoginController";
import { QueryProvider } from "@/shared/components/QueryProvider/QueryProvider";
import type { LoginPortal } from "@/shared/lib/loginPortal";

const PORTAL_COPY = {
  marketer: {
    heading: "ログイン",
    alternate: { href: "/admin/login", label: "管理ユーザーの方はこちら" },
  },
  admin: {
    heading: "管理ユーザーのログイン",
    alternate: { href: "/login", label: "マーケターユーザーの方はこちら" },
  },
} as const;

type LoginContainerProps = {
  portal: LoginPortal;
  nextPath: string;
  initialFormError: string | null;
  notice: string | null;
};

export function LoginContainer(props: LoginContainerProps) {
  return <QueryProvider><LoginFormContainer {...props} /></QueryProvider>;
}

function LoginFormContainer(props: LoginContainerProps) {
  const controller = useLoginController(props);
  const copy = PORTAL_COPY[props.portal];
  return (
    <LoginView
      heading={copy.heading}
      alternateLink={copy.alternate}
      notice={props.notice}
      {...controller.state}
      emailRef={controller.emailRef}
      passwordRef={controller.passwordRef}
      formErrorRef={controller.formErrorRef}
      onSubmit={controller.onSubmit}
      onEmailChange={controller.onEmailChange}
      onPasswordChange={controller.onPasswordChange}
      onPasswordVisibilityToggle={controller.onPasswordVisibilityToggle}
      onReload={controller.onReload}
    />
  );
}
