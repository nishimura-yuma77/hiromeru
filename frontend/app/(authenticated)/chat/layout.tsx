import { dehydrate, HydrationBoundary } from "@tanstack/react-query";
import { ChatWorkspace } from "@/features/chat/components/ChatWorkspace";
import { sessionKeys } from "@/features/chat/queries/sessionKeys";
import { getSessions } from "@/features/chat/server";
import { makeQueryClient } from "@/shared/api/queryClient";

export default async function ChatLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const sessions = await getSessions();
  const client = makeQueryClient();
  client.setQueryData(sessionKeys.list(), { pages: [sessions], pageParams: [null] });
  return <HydrationBoundary state={dehydrate(client)}><ChatWorkspace initialSessions={sessions}>{children}</ChatWorkspace></HydrationBoundary>;
}
