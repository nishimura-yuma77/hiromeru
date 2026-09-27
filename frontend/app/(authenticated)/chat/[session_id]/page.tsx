import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Conversation } from "@/features/chat/components/Conversation";
import { getSessionHistory } from "@/features/chat/server";
import type { SessionHistory } from "@/features/chat/types";
import { ApiError } from "@/shared/api/ApiError";

export const metadata: Metadata = { title: "会話 | Hiromeru" };

export default async function SessionPage({ params }: { params: Promise<{ session_id: string }> }) {
  const sessionId = Number((await params).session_id);
  if (!Number.isSafeInteger(sessionId) || sessionId <= 0) notFound();
  let history: SessionHistory;
  try {
    history = await getSessionHistory(sessionId);
  } catch (error) {
    if (error instanceof ApiError && error.code === "AGENT_SESSION_NOT_FOUND") notFound();
    throw error;
  }
  return <Conversation initialHistory={history} />;
}
