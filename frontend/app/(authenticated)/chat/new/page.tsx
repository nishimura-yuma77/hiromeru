import type { Metadata } from "next";

import { Conversation } from "@/features/chat/components/Conversation";

export const metadata: Metadata = { title: "新しい会話 | Hiromeru" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function inheritedDraft(params: Record<string, string | string[] | undefined>) {
  const campaignId = typeof params.campaign_id === "string" ? Number(params.campaign_id) : NaN;
  const postId = typeof params.post_id === "string" ? Number(params.post_id) : NaN;
  const intent = typeof params.intent === "string" ? params.intent : "";
  const validCampaign = Number.isSafeInteger(campaignId) && campaignId > 0;
  const validPost = Number.isSafeInteger(postId) && postId > 0;

  if (validCampaign && !validPost && intent === "create_post") return `施策ID ${campaignId}のX投稿案を作りたいです`;
  if (validCampaign && !validPost && intent === "revise_campaign") return `施策ID ${campaignId}の内容を変更したいです`;
  if (validPost && !validCampaign && intent === "discuss_post") return `投稿ID ${postId}について相談したいです`;
  return "";
}

export default async function NewChatPage({ searchParams }: { searchParams: SearchParams }) {
  return <Conversation initialDraft={inheritedDraft(await searchParams)} initialHistory={null} />;
}
