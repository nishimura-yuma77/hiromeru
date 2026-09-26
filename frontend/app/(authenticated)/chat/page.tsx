import type { Metadata } from "next";

import { ChatIndex } from "@/features/chat/components/ChatIndex";

export const metadata: Metadata = { title: "会話 | Hiromeru" };

export default function ChatPage() {
  return <ChatIndex />;
}
