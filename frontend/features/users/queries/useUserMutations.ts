"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  inviteUser,
  reactivateUser,
  resendInvitation,
  suspendUser,
  updateUser,
  type InviteUserRequest,
  type UpdateUserRequest,
} from "@/features/users/api/userAdminClient";
import { userKeys } from "@/features/users/queries/userKeys";

// 結果の分からない状態変更は自動で再送しない（API_DESIGN 11.2）。成否にかかわらず一覧を
// 再取得し、保存済みの状態を画面へ反映する。
function useRefetchingMutation<TVariables, TResult>(fn: (variables: TVariables) => Promise<TResult>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => client.invalidateQueries({ queryKey: userKeys.lists }),
  });
}

export function useInviteUserMutation() {
  return useRefetchingMutation((request: InviteUserRequest) => inviteUser(request));
}

export function useUpdateUserMutation() {
  return useRefetchingMutation(({ userId, ...request }: UpdateUserRequest & { userId: number }) =>
    updateUser(userId, request),
  );
}

export function useSuspendUserMutation() {
  return useRefetchingMutation((userId: number) => suspendUser(userId));
}

export function useReactivateUserMutation() {
  return useRefetchingMutation((userId: number) => reactivateUser(userId));
}

export function useResendInvitationMutation() {
  return useRefetchingMutation((userId: number) => resendInvitation(userId));
}
