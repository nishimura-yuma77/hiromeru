"use client";

import { InvitationAcceptView } from "@/features/invitations/components/InvitationAcceptView/InvitationAcceptView";
import { useInvitationAcceptController } from "@/features/invitations/controllers/useInvitationAcceptController";

export function InvitationAcceptContainer({ token }: { token: string | null }) {
  const controller = useInvitationAcceptController(token);
  return (
    <InvitationAcceptView
      {...controller.state}
      passwordRef={controller.passwordRef}
      onSubmit={controller.onSubmit}
      onPasswordChange={controller.onPasswordChange}
      onPasswordVisibilityToggle={controller.onPasswordVisibilityToggle}
    />
  );
}
