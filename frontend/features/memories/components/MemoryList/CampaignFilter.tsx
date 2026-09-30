import Link from "next/link";
import { Button } from "@/shared/components/Button/Button";
import { Spinner } from "@/shared/components/Spinner/Spinner";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import { searchCampaigns, type CampaignOption } from "@/features/memories/api/searchCampaigns";
import { Input } from "@/shared/components/Input/Input";

import styles from "./MemoryList.module.scss";

export function CampaignFilter({ initialCampaign, query }: { initialCampaign: CampaignOption | null; query: string }) {
  const [value, setValue] = useState(initialCampaign?.title ?? "");
  const [selectedId, setSelectedId] = useState<number | null>(initialCampaign?.id ?? null);
  const [options, setOptions] = useState<CampaignOption[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!expanded) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const response = await searchCampaigns(value.trim(), controller.signal);
        if (!controller.signal.aborted) {
          setOptions(response.campaigns);
          setActiveIndex(-1);
        }
      } catch {
        if (!controller.signal.aborted) {
          setOptions([]);
          setError("施策を検索できませんでした。もう一度入力してください。");
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [expanded, value]);

  useEffect(() => {
    function closeOnOutsideClick(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) setExpanded(false);
    }
    document.addEventListener("pointerdown", closeOnOutsideClick);
    return () => document.removeEventListener("pointerdown", closeOnOutsideClick);
  }, []);

  function choose(campaign: CampaignOption) {
    setValue(campaign.title);
    setSelectedId(campaign.id);
    setExpanded(false);
    setError("");
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") { setExpanded(false); return; }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setExpanded(true);
      if (!options.length) return;
      setActiveIndex((current) => event.key === "ArrowDown"
        ? Math.min(current + 1, options.length - 1)
        : Math.max(current - 1, 0));
    }
    if (event.key === "Enter" && expanded && activeIndex >= 0 && options[activeIndex]) {
      event.preventDefault();
      choose(options[activeIndex]);
    }
  }

  function validate(event: FormEvent<HTMLFormElement>) {
    if (value.trim() && selectedId === null) {
      event.preventDefault();
      setExpanded(true);
      setError("候補から施策を選択してください。");
    }
  }

  return (
    <form action="/memories" method="get" className={styles.searchForm} onSubmit={validate}>
      <label className={styles.searchField}>
        <span className={styles.visuallyHidden}>記憶を検索</span>
        <Input leadingIcon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.5 15.5 5 5" /></svg>} type="search" name="query" defaultValue={query} maxLength={1000} placeholder="記憶を検索" />
      </label>
      <div className={styles.campaignField} ref={containerRef}>
        <label className={styles.visuallyHidden} htmlFor="memory-campaign-filter">施策で絞り込み</label>
        <Input
          id="memory-campaign-filter"
          type="text"
          value={value}
          onFocus={() => setExpanded(true)}
          onChange={(event) => { setValue(event.target.value); setSelectedId(null); setOptions([]); setActiveIndex(-1); setExpanded(true); setError(""); }}
          onKeyDown={onKeyDown}
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls="memory-campaign-options"
          aria-activedescendant={expanded && activeIndex >= 0 && options[activeIndex] ? `memory-campaign-option-${options[activeIndex].id}` : undefined}
          aria-describedby={error ? "memory-campaign-error" : undefined}
          aria-invalid={Boolean(error)}
          placeholder="施策で絞り込み"
          autoComplete="off"
        />
        <input type="hidden" name="campaign_id" value={selectedId ?? ""} />
        {expanded ? <div className={styles.campaignOptions} id="memory-campaign-options" role="listbox" aria-label="施策の候補">
          {loading ? <p className={styles.campaignLoading} role="status"><Spinner size="small" />施策を検索中…</p> : options.length ? options.map((campaign, index) => (
            <Button variant="ghost" size="small" role="option" aria-selected={index === activeIndex} id={`memory-campaign-option-${campaign.id}`} key={campaign.id} onClick={() => choose(campaign)}>{campaign.title}</Button>
          )) : <p>{error || "候補がありません"}</p>}
        </div> : null}
        {error ? <p id="memory-campaign-error" className={styles.filterError} role="alert">{error}</p> : null}
      </div>
      <Button size="small" type="submit">検索</Button>
      <Link href="/memories" className={styles.clearLink}>条件をクリア</Link>
    </form>
  );
}
