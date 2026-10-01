"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import type { CampaignOption } from "@/features/campaigns/queries/campaignKeys";
import { useCampaignOptionsQuery } from "@/features/campaigns/queries/campaignQueries";
import type { CampaignListItem } from "@/features/campaigns/types/campaign";
import { parsePostListParams, type PostListParams } from "@/features/posts/utils/postParams";
import { Button } from "@/shared/components/Button/Button";
import { Input } from "@/shared/components/Input/Input";
import { Disclosure } from "@/shared/components/Disclosure/Disclosure";
import { SearchCombobox } from "@/shared/components/SearchCombobox/SearchCombobox";

import styles from "./PostList.module.scss";

export function PostFilters({ params, selectedCampaign, onApply }: {
  params: PostListParams;
  selectedCampaign: CampaignOption | null;
  onApply: (params: PostListParams, campaign: CampaignOption | null) => void;
}) {
  const [value, setValue] = useState(selectedCampaign?.title ?? "");
  const [selectedId, setSelectedId] = useState<number | null>(selectedCampaign?.id ?? null);
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
    applyFilters(formRef.current, campaign);
  }

  function applyFilters(form: HTMLFormElement | null, campaignOverride?: CampaignOption) {
    if (!form) return;
    const campaignId = campaignOverride?.id ?? selectedId;
    if (value.trim() && campaignId === null) {
      setExpanded(true);
      setFieldError("候補から施策を選択してください。");
      return;
    }
    const from = form.elements.namedItem("published_from") as HTMLInputElement;
    const to = form.elements.namedItem("published_to") as HTMLInputElement;
    to.setCustomValidity("");
    if (from.value && to.value && from.value > to.value) {
      to.setCustomValidity("終了日は開始日以降の日付を指定してください。");
      to.reportValidity();
      return;
    }
    const fields = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
    fields.campaign_id = campaignId === null ? "" : String(campaignId);
    if (fields.query?.trim()) delete fields.sort;
    const campaign = campaignOverride ?? (campaignId === selectedCampaign?.id ? selectedCampaign : options.find((option) => option.id === campaignId) ?? null);
    onApply(parsePostListParams(fields), campaign);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    applyFilters(event.currentTarget);
  }

  function clearFilters() {
    setValue("");
    setSelectedId(null);
    setFieldError("");
    setExpanded(false);
    const form = formRef.current;
    if (form) {
      (form.elements.namedItem("query") as HTMLInputElement).value = "";
      (form.elements.namedItem("published_from") as HTMLInputElement).value = "";
      const to = form.elements.namedItem("published_to") as HTMLInputElement;
      to.value = "";
      to.setCustomValidity("");
    }
    onApply(parsePostListParams({}), null);
  }

  const hasAdvancedFilters = Boolean(params.publishedFrom || params.publishedTo);

  return (
    <section aria-labelledby="post-filter-title">
      <h2 className={styles.visuallyHidden} id="post-filter-title">投稿を探す</h2>
      <form ref={formRef} id="post-filters" className={styles.filterForm} onSubmit={submit}>
        <div className={styles.searchField}>
          <label className={styles.visuallyHidden} htmlFor="post-query">投稿本文を検索</label>
          <Input id="post-query" type="search" name="query" defaultValue={params.query} maxLength={1000} placeholder="投稿本文を検索"
            leadingIcon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.5 15.5 5 5" /></svg>}
          />
        </div>
        <div className={styles.campaignField}>
          <SearchCombobox id="post-campaign-filter" label="施策で絞り込み" hideLabel value={value} placeholder="施策で絞り込み"
            onValueChange={(nextValue) => { setValue(nextValue); setSelectedId(null); setFieldError(""); }}
            options={options} onSelect={choose} open={expanded} onOpenChange={setExpanded}
            loading={loading} searchError={searchError} fieldError={fieldError}
            renderOption={(campaign) => <>{campaign.title}{campaign.archived_at ? "（アーカイブ済み）" : ""}</>}
          />
          <input type="hidden" name="campaign_id" value={selectedId ?? ""} />
        </div>
        <label className={styles.sortField}>
          <span className={styles.visuallyHidden}>並び順</span>
          <select name="sort" defaultValue={params.query ? "relevance" : params.sort} disabled={Boolean(params.query)} onChange={(event) => event.currentTarget.form?.requestSubmit()}>
            {params.query ? <option value="relevance">関連度順</option> : null}
            <option value="published_at_desc">新しい順</option>
            <option value="published_at_asc">古い順</option>
            <option value="x_pv_count_desc">初週PVの多い順</option>
            <option value="x_pv_count_asc">初週PVの少ない順</option>
          </select>
        </label>
        <div className={styles.filterActions}>
          <Button type="submit" size="small">検索</Button>
          <Button variant="ghost" size="small" onClick={clearFilters}>条件をクリア</Button>
        </div>
      </form>
      <div className={styles.advancedFilters}>
        <Disclosure key={`${params.publishedFrom}:${params.publishedTo}`} defaultOpen={hasAdvancedFilters} summary={`詳細条件${hasAdvancedFilters ? "（適用中）" : ""}`}>
          <div className={styles.advancedContent}>
            <label>公開日の開始<Input form="post-filters" type="date" name="published_from" defaultValue={params.publishedFrom} /></label>
            <label>公開日の終了<Input form="post-filters" type="date" name="published_to" defaultValue={params.publishedTo} onInput={(event) => event.currentTarget.setCustomValidity("")} /></label>
          </div>
        </Disclosure>
      </div>
      {params.query ? <p className={styles.hint}>検索中は関連度順で表示し、並び替えは利用できません。</p> : null}
    </section>
  );
}
