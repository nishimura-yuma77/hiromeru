import type { Metadata } from "next";
import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { redirect } from "next/navigation";

import { getCurrentUser } from "@/features/auth/server/getCurrentUser";
import { UserManagementContainer } from "@/features/users/containers/UserManagementContainer";
import { userKeys } from "@/features/users/queries/userKeys";
import { listUsers } from "@/features/users/server/listUsers";
import { parsePageParam } from "@/features/users/types/user";
import { ApiError } from "@/shared/api/ApiError";
import { makeQueryClient } from "@/shared/api/queryClient";

export const metadata: Metadata = {
  title: "ユーザー管理 | Hiromeru",
};

type UsersPageProps = {
  searchParams: Promise<{ page?: string | string[] }>;
};

export default async function UsersPage({ searchParams }: UsersPageProps) {
  const page = parsePageParam((await searchParams).page);
  const [currentUser, list] = await Promise.all([
    getCurrentUser(),
    listUsers(page).catch((error: unknown) => {
      if (error instanceof ApiError && error.code === "INVALID_ARGUMENT") {
        return null;
      }
      throw error;
    }),
  ]);
  if (list === null) {
    // 範囲外のpageは先頭ページへ戻す（SCREEN_DESIGN SC-11）。
    redirect("/admin/users?page=1");
  }
  const client = makeQueryClient();
  client.setQueryData(userKeys.list(page), list);
  return (
    <HydrationBoundary state={dehydrate(client)}>
      <UserManagementContainer currentUserId={currentUser.userId} />
    </HydrationBoundary>
  );
}
