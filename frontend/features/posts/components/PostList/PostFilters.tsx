"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { searchCampaigns, type CampaignOption } from "@/features/posts/api/searchCampaigns";
import type { PostListParams } from "@/features/posts/utils/postParams";
import { Button } from "@/shared/components/Button/Button";
import { Input } from "@/shared/components/Input/Input";
import { Disclosure } from "@/shared/components/Disclosure/Disclosure";
import { SearchCombobox } from "@/shared/components/SearchCombobox/SearchCombobox";

import styles from "./PostList.module.scss";

export function PostFilters({ params, selectedCampaign }: { params: PostListParams; selectedCampaign: CampaignOption | null }) {
  const [value, setValue] = useState(selectedCampaign?.title ?? "");
  const [selectedId, setSelectedId] = useState<number | null>(selectedCampaign?.id ?? null);
  const [options, setOptions] = useState<CampaignOption[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [fieldError, setFieldError] = useState("");
  const formRef = useRef<HTMLFormElement>(null);

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
    window.setTimeout(() => formRef.current?.requestSubmit(), 0);
  }

  function validate(event: FormEvent<HTMLFormElement>) {
    if (value.trim() && selectedId === null) {
      event.preventDefault();
      setExpanded(true);
      setFieldError("候補から施策を選択してください。");
      return;
    }
    const from = event.currentTarget.elements.namedItem("published_from") as HTMLInputElement;
    const to = event.currentTarget.elements.namedItem("published_to") as HTMLInputElement;
    to.setCustomValidity("");
    if (from.value && to.value && from.value > to.value) {
      event.preventDefault();
      to.setCustomValidity("終了日は開始日以降の日付を指定してください。");
      to.reportValidity();
    }
    const query = event.currentTarget.elements.namedItem("query") as HTMLInputElement;
    if (query.value.trim()) (event.currentTarget.elements.namedItem("sort") as HTMLSelectElement).disabled = true;
  }

  const hasAdvancedFilters = Boolean(params.publishedFrom || params.publishedTo);

  return (
    <section className={styles.filters} aria-labelledby="post-filter-title">
      <h2 className={styles.visuallyHidden} id="post-filter-title">投稿を探す</h2>
      <form ref={formRef} id="post-filters" action="/posts" method="get" className={styles.filterForm} onSubmit={validate}>
        <div className={styles.searchField}>
          <label className={styles.visuallyHidden} htmlFor="post-query">投稿本文を検索</label>
          <Input id="post-query" type="search" name="query" defaultValue={params.query} maxLength={1000} placeholder="投稿本文を検索"
            leadingIcon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.5 15.5 5 5" /></svg>}
          />
        </div>
        <div className={styles.campaignField}>
          <SearchCombobox id="post-campaign-filter" label="施策で絞り込み" hideLabel value={value} placeholder="施策で絞り込み"
            onValueChange={(nextValue) => { setValue(nextValue); setSelectedId(null); setOptions([]); setLoading(true); setFieldError(""); setSearchError(""); }}
            options={options} onSelect={choose} open={expanded} onOpenChange={(nextOpen) => { if (nextOpen && !expanded) setLoading(true); setExpanded(nextOpen); }}
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
          <Link href="/posts">条件をクリア</Link>
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
