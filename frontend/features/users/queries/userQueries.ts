"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { listUsersBrowser } from "@/features/users/api/userAdminClient";
import { userKeys } from "@/features/users/queries/userKeys";

export function useUserListQuery(page: number) {
  return useQuery({
    queryKey: userKeys.list(page),
    queryFn: ({ signal }) => listUsersBrowser(page, signal),
    placeholderData: keepPreviousData,
  });
}
