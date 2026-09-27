import { notFound, redirect } from "next/navigation";

import { parsePositiveId } from "@/features/campaigns/utils/campaignParams";

type OpenCampaignPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function OpenCampaignPage({ searchParams }: OpenCampaignPageProps) {
  const rawId = (await searchParams).id;
  const id = parsePositiveId(typeof rawId === "string" ? rawId : "");
  if (id === null) notFound();
  redirect(`/campaigns/${id}`);
}
