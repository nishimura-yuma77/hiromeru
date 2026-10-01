"use client";

import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Button } from "@/shared/components/Button/Button";
import { Input } from "@/shared/components/Input/Input";
import { Disclosure } from "@/shared/components/Disclosure/Disclosure";
import { ListStatus } from "@/shared/components/ListStatus/ListStatus";
import { useInvalidCursorRecovery, useQueryNavigation } from "@/shared/lib/useQueryNavigation";

import type {
  CampaignListItem,
  CampaignListResponse,
  MetricsSummary,
} from "@/features/campaigns/types/campaign";
import { listCampaignsBrowser } from "@/features/campaigns/api/listCampaignsBrowser";
import { campaignKeys } from "@/features/campaigns/queries/campaignKeys";
import { useCampaignListQuery } from "@/features/campaigns/queries/campaignQueries";
import {
  campaignPageHref,
  parsePositiveId,
  parseCampaignListParams,
  type CampaignListParams,
} from "@/features/campaigns/utils/campaignParams";

import styles from "./CampaignList.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const rateFormat = new Intl.NumberFormat("ja-JP", {
  style: "percent",
  maximumFractionDigits: 1,
});
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  timeZone: "Asia/Tokyo",
});
const dateTimeFormat = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "日時不明";
  const parts = dateFormat.formatToParts(date);
  return ["year", "month", "day"].map((part) => parts.find((item) => item.type === part)?.value).join("-");
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "日時不明" : dateTimeFormat.format(date);
}

function excludedCount(summary: MetricsSummary): number {
  return Math.max(
    0,
    summary.post_count - summary.completed_count - summary.pending_count - summary.failed_count,
  );
}

function metricValue(summary: MetricsSummary, value: number): string {
  return summary.completed_count > 0 ? numberFormat.format(value) : "—";
}

function rateValue(summary: MetricsSummary): string {
  return summary.completed_count > 0 && summary.landing_rate !== null
    ? rateFormat.format(summary.landing_rate)
    : "—";
}

function metricExplanation(summary: MetricsSummary): string | null {
  if (summary.post_count === 0) return "公開済み投稿なし";
  if (summary.completed_count > 0) return null;
  if (summary.pending_count > 0) return "集計待ち";
  if (summary.failed_count > 0) return "集計結果を取得できません";
  return "計測対象の投稿なし";
}

function StatusBadges({ summary }: { summary: MetricsSummary }) {
  const excluded = excludedCount(summary);
  const statuses = [
    ["計測済み", summary.completed_count],
    ["待ち", summary.pending_count],
    ["失敗", summary.failed_count],
    ["対象外", excluded],
  ] as const;
  const visibleStatuses = statuses.filter(([, count]) => count > 0);

  if (visibleStatuses.length === 0) {
    return null;
  }

  return (
    <div className={styles.statuses} aria-label="計測状況">
      {visibleStatuses.map(([label, count]) => (
        <span key={label}>{label} {numberFormat.format(count)}</span>
      ))}
    </div>
  );
}

function MetricValues({ summary }: { summary: MetricsSummary }) {
  const explanation = metricExplanation(summary);
  return (
    <>
      <dl className={styles.metrics}>
        <div><dt>公開済み</dt><dd>{numberFormat.format(summary.post_count)}件</dd></div>
        <div><dt>初週PV</dt><dd>{metricValue(summary, summary.x_pv_count)}</dd></div>
        <div><dt>流入ユーザー</dt><dd>{metricValue(summary, summary.landing_user_count)}</dd></div>
        <div><dt>流入率</dt><dd>{rateValue(summary)}</dd></div>
      </dl>
      {explanation ? <p className={styles.metricExplanation}>{explanation}</p> : null}
      <StatusBadges summary={summary} />
    </>
  );
}

function CampaignStatus({ archived }: { archived: boolean }) {
  return <span className={archived ? styles.archivedBadge : styles.activeBadge}>{archived ? "アーカイブ済み" : "有効"}</span>;
}

function CampaignCards({ campaigns }: { campaigns: CampaignListItem[] }) {
  return (
    <div className={styles.mobileCards}>
      {campaigns.map((campaign) => (
        <article className={styles.card} key={campaign.id}>
          <div className={styles.cardMain}>
            <div className={styles.recordLine}>
              <p className={styles.recordId}>施策ID {campaign.id}</p>
              <CampaignStatus archived={Boolean(campaign.archived_at)} />
            </div>
            <h3>{campaign.title}</h3>
            <p className={styles.objective}>{campaign.objective}</p>
          </div>
          <p className={styles.postCount}>公開済み {numberFormat.format(campaign.metrics_summary.post_count)}件</p>
          <MetricValues summary={campaign.metrics_summary} />
          <p className={styles.dates}>
            <time dateTime={campaign.created_at}>作成 {formatDate(campaign.created_at)}</time>
            <time dateTime={campaign.updated_at}>更新 {formatDate(campaign.updated_at)}</time>
          </p>
          <Link className={styles.cardLink} href={`/campaigns/${campaign.id}`}>詳細を見る</Link>
        </article>
      ))}
    </div>
  );
}

function CampaignTable({ campaigns }: { campaigns: CampaignListItem[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <caption className={styles.srOnly}>施策一覧</caption>
        <thead>
          <tr>
            <th scope="col">施策</th>
            <th scope="col">成果</th>
            <th scope="col">日時</th>
          </tr>
        </thead>
        <tbody>
          {campaigns.map((campaign) => {
            const summary = campaign.metrics_summary;
            const explanation = metricExplanation(summary);
            return (
              <tr key={campaign.id}>
                <th scope="row">
                  <div className={styles.titleLine}>
                    <Link href={`/campaigns/${campaign.id}`}>{campaign.title}</Link>
                    <CampaignStatus archived={Boolean(campaign.archived_at)} />
                  </div>
                  <p className={styles.tableDescription}><span className={styles.tableId}>ID {campaign.id}</span>{campaign.objective}</p>
                </th>
                <td className={styles.resultCell}>
                  <div><strong>{metricValue(summary, summary.x_pv_count)}</strong> PV</div>
                  <div><strong>{metricValue(summary, summary.landing_user_count)}</strong> 流入 <span className={styles.rate}>{rateValue(summary)}</span></div>
                  <span className={styles.postCount}>公開済み {numberFormat.format(summary.post_count)}件</span>
                  {explanation ? <span className={styles.metricExplanation}>{explanation}</span> : null}
                  <StatusBadges summary={summary} />
                </td>
                <td className={styles.dateCell}>
                  <time dateTime={campaign.created_at} aria-label={`作成 ${formatDateTime(campaign.created_at)}`}>{formatDate(campaign.created_at)}</time>
                  <time dateTime={campaign.updated_at} aria-label={`更新 ${formatDateTime(campaign.updated_at)}`}>更新 {formatDate(campaign.updated_at)}</time>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

type CampaignListProps = {
  response: CampaignListResponse;
  params: CampaignListParams;
};

function parseCampaignSearch(search: string) {
  return parseCampaignListParams(Object.fromEntries(new URLSearchParams(search)));
}

function campaignHref(params: CampaignListParams) {
  return campaignPageHref(params, params.cursor || undefined);
}
function withoutCampaignCursor(params: CampaignListParams) { return params.cursor ? { ...params, cursor: "" } : null; }

export function CampaignList({ response: initialResponse }: CampaignListProps) {
  const router = useRouter();
  const navigation = useQueryNavigation({
    parse: parseCampaignSearch,
    key: campaignKeys.list,
    fetch: listCampaignsBrowser,
    href: campaignHref,
    withoutCursor: withoutCampaignCursor,
    fallbackError: "施策を読み込めませんでした。",
  });
  const { params } = navigation;
  const query = useCampaignListQuery(params);
  useInvalidCursorRecovery(query.error, params, withoutCampaignCursor, navigation.apply);
  const response = query.data ?? initialResponse;
  const loading = navigation.pending || query.isFetching;
  const error = navigation.pending ? "" : navigation.error || (query.error instanceof Error ? query.error.message : "");
  const load = (nextParams: CampaignListParams) => void navigation.apply(nextParams);
  const hasAdvancedFilters = Boolean(params.createdFrom || params.createdTo);
  const hasFilters = Boolean(
    params.query || params.archived !== "all" || hasAdvancedFilters,
  );

  function validateDateRange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const from = form.elements.namedItem("created_from") as HTMLInputElement;
    const to = form.elements.namedItem("created_to") as HTMLInputElement;
    from.setCustomValidity("");
    to.setCustomValidity("");
    if (from.value && to.value && from.value > to.value) {
      to.setCustomValidity("終了日は開始日以降の日付を指定してください。");
      to.reportValidity();
      return;
    }
    const fields = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;
    void load(parseCampaignListParams(fields));
  }

  function validateDirectId(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem("id") as HTMLInputElement;
    input.setCustomValidity("");
    if (parsePositiveId(input.value.trim()) === null) {
      input.setCustomValidity("施策IDは1以上の整数で入力してください。");
      input.reportValidity();
      return;
    }
    router.push(`/campaigns/${input.value.trim()}`);
  }

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <h1>施策</h1>
        <Link className={styles.primaryLink} href="/chat/new">＋ 新しい施策を作る</Link>
      </header>

      <section className={styles.filters} aria-labelledby="campaign-search-title">
        <h2 className={styles.srOnly} id="campaign-search-title">施策を探す</h2>
        <form key={`${params.query}:${params.archived}`} id="campaign-filters" className={styles.filterForm} onSubmit={validateDateRange}>
          <label className={styles.searchField}>
            <span className={styles.srOnly}>施策を検索</span>
            <Input
              leadingIcon={<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="10.8" cy="10.8" r="6.2" /><path d="m15.5 15.5 5 5" /></svg>}
              type="search"
              name="query"
              defaultValue={params.query}
              maxLength={1000}
              placeholder="施策を検索"
            />
          </label>
          <label className={styles.statusField}>
            <span className={styles.srOnly}>状態で絞り込む</span>
            <select name="archived" defaultValue={params.archived} onChange={(event) => event.currentTarget.form?.requestSubmit()}>
              <option value="all">ステータスで絞り込む</option>
              <option value="active">有効</option>
              <option value="archived">アーカイブ済み</option>
            </select>
          </label>
          <Button size="small" type="submit">検索</Button>
        </form>
        <div className={styles.advancedFilters}>
          <Disclosure key={`${params.createdFrom}:${params.createdTo}`} defaultOpen={hasAdvancedFilters} summary={`詳細条件${hasAdvancedFilters ? "（適用中）" : ""}`}>
          <div className={styles.advancedContent}>
            <div className={styles.advancedFields}>
              <label>
                <span>作成日の開始</span>
                <Input form="campaign-filters" type="date" name="created_from" defaultValue={params.createdFrom} />
              </label>
              <label>
                <span>作成日の終了</span>
                 <Input form="campaign-filters" type="date" name="created_to" defaultValue={params.createdTo} onInput={(event) => event.currentTarget.setCustomValidity("")} />
              </label>
              <div className={styles.filterActions}>
                <Button form="campaign-filters" size="small" type="submit">条件を適用</Button>
                 <Button variant="ghost" size="small" onClick={() => void load(parseCampaignListParams({}))}>条件をクリア</Button>
              </div>
            </div>
            <form className={styles.idForm} onSubmit={validateDirectId}>
              <label>
                <span>施策IDで直接開く</span>
                <Input type="text" name="id" inputMode="numeric" pattern="[1-9][0-9]*" required onInput={(event) => event.currentTarget.setCustomValidity("")} />
              </label>
              <Button size="small" type="submit">開く</Button>
            </form>
          </div>
          </Disclosure>
        </div>
      </section>

       <section className={styles.results} aria-labelledby="campaign-results-title">
          <ListStatus loading={loading} error={error} onRetry={() => navigation.error ? navigation.retry() : void query.refetch()} loadingLabel="施策を読み込んでいます" />
        <div className={params.query ? styles.resultHeading : styles.srOnly}>
          <h2 id="campaign-results-title">{params.query ? `「${params.query}」に近い施策` : "施策一覧"}</h2>
          {params.query ? <p>施策の内容をもとに関連度順で表示しています。</p> : null}
        </div>

        {response.campaigns.length === 0 ? (
          <div className={styles.empty}>
            <h3>{hasFilters ? "条件に合う施策がありません" : "まだ施策がありません"}</h3>
            <p>{hasFilters ? "検索語や作成日の範囲を変更してください。" : "Hiromeru AIと相談して、最初の施策を作成しましょう。"}</p>
             {hasFilters ? <Button variant="ghost" size="small" onClick={() => void load(parseCampaignListParams({}))}>検索条件をクリア</Button> : <Link href="/chat/new">新しい施策を作る</Link>}
          </div>
        ) : (
          <>
            <CampaignTable campaigns={response.campaigns} />
            <CampaignCards campaigns={response.campaigns} />
          </>
        )}

        {!params.query && (params.cursor || response.next_cursor) ? (
          <nav className={styles.pagination} aria-label="施策一覧のページ移動">
             {params.cursor ? <Button variant="ghost" size="small" disabled={loading} onClick={() => void load({ ...params, cursor: "" })}>先頭へ</Button> : null}
             {response.next_cursor ? <Button variant="ghost" size="small" disabled={loading} onClick={() => void load({ ...params, cursor: response.next_cursor ?? "" })}>次の20件</Button> : null}
          </nav>
        ) : null}
      </section>
    </main>
  );
}
