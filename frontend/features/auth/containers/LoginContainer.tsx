"use client";

import { LoginView } from "@/features/auth/components/LoginView/LoginView";
import { useLoginController } from "@/features/auth/controllers/useLoginController";

type LoginContainerProps = {
  nextPath: string;
  initialFormError: string | null;
};

export function LoginContainer(props: LoginContainerProps) {
  const controller = useLoginController(props);
  return (
    <LoginView
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
