import type { Metadata } from "next";

import { InvitationAcceptContainer } from "@/features/invitations/containers/InvitationAcceptContainer";

export const metadata: Metadata = {
  title: "パスワードの設定 | Hiromeru",
  referrer: "no-referrer",
};

export const dynamic = "force-dynamic";

type InvitationAcceptPageProps = {
  searchParams: Promise<{ token?: string | string[] }>;
};

// 初期表示ではリンクを検証するAPIを呼ばない。tokenはパスワード設定が完了するまでURLに保持する。
export default async function InvitationAcceptPage({ searchParams }: InvitationAcceptPageProps) {
  const { token } = await searchParams;
  const value = Array.isArray(token) ? token[0] : token;
  return <InvitationAcceptContainer token={value && value.length > 0 ? value : null} />;
}
