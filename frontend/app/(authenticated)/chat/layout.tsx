import { ChatWorkspace } from "@/features/chat/components/ChatWorkspace";
import { getSessions } from "@/features/chat/server";

export default async function ChatLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const sessions = await getSessions();
  return <ChatWorkspace initialSessions={sessions}>{children}</ChatWorkspace>;
}
