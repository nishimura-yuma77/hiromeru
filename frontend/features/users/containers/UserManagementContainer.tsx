"use client";

import { UserDialogs } from "@/features/users/components/UserDialogs/UserDialogs";
import { UserManagementView } from "@/features/users/components/UserManagementView/UserManagementView";
import {
  canChangeUserType,
  canSuspendUser,
  useUserManagementController,
} from "@/features/users/controllers/useUserManagementController";

export function UserManagementContainer({ currentUserId }: { currentUserId: number }) {
  const controller = useUserManagementController();
  const { state, selectedUser } = controller;
  return (
    <UserManagementView
      list={controller.list}
      currentUserId={currentUserId}
      isLoading={controller.isListLoading}
      listError={controller.listError}
      notice={state.notice}
      onInvite={controller.openInvite}
      onOperate={controller.openOperation}
      onPage={controller.goToPage}
      onRetry={controller.refetch}
      onDismissNotice={controller.dismissNotice}
      dialogs={
        <UserDialogs
          dialog={state.dialog}
          selectedUser={selectedUser}
          canChangeType={selectedUser ? canChangeUserType(selectedUser, currentUserId) : false}
          canSuspend={selectedUser ? canSuspendUser(selectedUser, currentUserId) : false}
          isPending={state.isPending}
          dialogError={state.dialogError}
          onClose={controller.close}
          onInviteChange={controller.changeInvite}
          onInviteSubmit={controller.submitInvite}
          onNameChange={controller.changeOperationName}
          onTypeChange={controller.changeOperationType}
          onSave={controller.saveOperation}
          onOpenConfirm={controller.openConfirm}
          onCancelConfirm={controller.cancelConfirm}
          onConfirm={() => void controller.confirm()}
        />
      }
    />
  );
}
