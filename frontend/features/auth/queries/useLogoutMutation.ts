"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { logout } from "@/features/auth/api/authClient";

export function useLogoutMutation() {
  const client = useQueryClient();
  return useMutation({ mutationFn: logout, onSuccess: () => client.clear() });
}
