"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { login } from "@/features/auth/api/authClient";

export function useLoginMutation() {
  const client = useQueryClient();
  return useMutation({ mutationFn: login, onSuccess: () => client.clear() });
}
