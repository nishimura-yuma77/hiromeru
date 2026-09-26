import { MemoryList } from "@/features/memories/components/MemoryList/MemoryList";
import { listMemories } from "@/features/memories/server/listMemories";
import { parseMemoryListParams } from "@/features/memories/utils/memoryParams";

type MemoriesPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function MemoriesPage({ searchParams }: MemoriesPageProps) {
  const params = parseMemoryListParams(await searchParams);
  const response = await listMemories(params);
  return <MemoryList response={response} params={params} />;
}
