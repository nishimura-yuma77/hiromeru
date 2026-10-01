import Link from "next/link";
import { Button } from "@/shared/components/Button/Button";
import { useEffect, useState, type FormEvent } from "react";

import { searchCampaigns, type CampaignOption } from "@/features/memories/api/searchCampaigns";
import { Input } from "@/shared/components/Input/Input";
import { SearchCombobox } from "@/shared/components/SearchCombobox/SearchCombobox";

import styles from "./MemoryList.module.scss";

export function CampaignFilter({ initialCampaign, query }: { initialCampaign: CampaignOption | null; query: string }) {
  const [value, setValue] = useState(initialCampaign?.title ?? "");
  const [selectedId, setSelectedId] = useState<number | null>(initialCampaign?.id ?? null);
  const [options, setOptions] = useState<CampaignOption[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [fieldError, setFieldError] = useState("");

  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setSearchError("");
      try {
        const response = await searchCampaigns(value.trim(), controller.signal);
        if (!controller.signal.aborted) {
          setOptions(response.campaigns);
        }
      } catch {
        if (!controller.signal.aborted) {
          setOptions([]);
          setSearchError("施策を検索できませんでした。もう一度入力してください。");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [expanded, value]);

  function choose(campaign: CampaignOption) {
    setValue(campaign.title);
    setSelectedId(campaign.id);
    setFieldError("");
  }

  function validate(event: FormEvent<HTMLFormElement>) {
    if (value.trim() && selectedId === null) {
      event.preventDefault();
      setExpanded(true);
      setFieldError("候補から施策を選択してください。");
    }
  }

  return (
    <form action="/memories" method="get" className={styles.searchForm} onSubmit={validate}>
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
          onValueChange={(nextValue) => { setValue(nextValue); setSelectedId(null); setOptions([]); setLoading(true); setFieldError(""); setSearchError(""); }}
          options={options}
          onSelect={choose}
          open={expanded}
          onOpenChange={(nextOpen) => { if (nextOpen && !expanded) setLoading(true); setExpanded(nextOpen); }}
          loading={loading}
          searchError={searchError}
          fieldError={fieldError}
          placeholder="施策で絞り込み"
        />
        <input type="hidden" name="campaign_id" value={selectedId ?? ""} />
      </div>
      <Button size="small" type="submit">検索</Button>
      <Link href="/memories" className={styles.clearLink}>条件をクリア</Link>
    </form>
  );
}
