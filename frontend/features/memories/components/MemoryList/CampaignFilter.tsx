import { Button } from "@/shared/components/Button/Button";
import { useEffect, useRef, useState, type FormEvent } from "react";

import type { CampaignOption } from "@/features/campaigns/queries/campaignKeys";
import { useCampaignOptionsQuery } from "@/features/campaigns/queries/campaignQueries";
import type { CampaignListItem } from "@/features/campaigns/types/campaign";
import { parseMemoryListParams, type MemoryListParams } from "@/features/memories/utils/memoryParams";
import { Input } from "@/shared/components/Input/Input";
import { SearchCombobox } from "@/shared/components/SearchCombobox/SearchCombobox";

import styles from "./MemoryList.module.scss";

export function CampaignFilter({ initialCampaign, query, onApply }: {
  initialCampaign: CampaignOption | null;
  query: string;
  onApply: (params: MemoryListParams, campaign: CampaignOption | null) => void;
}) {
  const [value, setValue] = useState(initialCampaign?.title ?? "");
  const [selectedId, setSelectedId] = useState<number | null>(initialCampaign?.id ?? null);
  const [expanded, setExpanded] = useState(false);
  const [fieldError, setFieldError] = useState("");
  const [debounced, setDebounced] = useState(value.trim());
  const formRef = useRef<HTMLFormElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [value]);

  const candidates = useCampaignOptionsQuery({ query: debounced, enabled: expanded });
  const options = candidates.data?.campaigns ?? [];
  const loading = expanded && (debounced !== value.trim() || candidates.isFetching);
  const searchError = candidates.error instanceof Error ? candidates.error.message : "";

  function choose(campaign: CampaignListItem) {
    setValue(campaign.title);
    setSelectedId(campaign.id);
    setFieldError("");
  }

  function validate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (value.trim() && selectedId === null) {
      setExpanded(true);
      setFieldError("候補から施策を選択してください。");
      return;
    }
    const fields = Object.fromEntries(new FormData(event.currentTarget).entries()) as Record<string, string>;
    onApply(parseMemoryListParams(fields), selectedId === initialCampaign?.id ? initialCampaign : options.find((option) => option.id === selectedId) ?? null);
  }

  function clearFilters() {
    setValue("");
    setSelectedId(null);
    setFieldError("");
    setExpanded(false);
    const input = formRef.current?.elements.namedItem("query") as HTMLInputElement | undefined;
    if (input) input.value = "";
    onApply(parseMemoryListParams({}), null);
  }

  return (
    <form ref={formRef} className={styles.searchForm} onSubmit={validate}>
      <label className={styles.searchField}>
        <span className={styles.visuallyHidden}>記憶を検索</span>
        <Input leadingIcon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.5 15.5 5 5" /></svg>} type="search" name="query" defaultValue={query} maxLength={1000} placeholder="記憶を検索" />
      </label>
      <div className={styles.campaignField}>
        <SearchCombobox
          id="memory-campaign-filter"
          label="施策で絞り込み"
          hideLabel
          value={value}
          onValueChange={(nextValue) => { setValue(nextValue); setSelectedId(null); setFieldError(""); }}
          options={options}
          onSelect={choose}
          open={expanded}
          onOpenChange={setExpanded}
          loading={loading}
          searchError={searchError}
          fieldError={fieldError}
          placeholder="施策で絞り込み"
        />
        <input type="hidden" name="campaign_id" value={selectedId ?? ""} />
      </div>
      <Button size="small" type="submit">検索</Button>
      <Button variant="ghost" size="small" onClick={clearFilters}>条件をクリア</Button>
    </form>
  );
}
