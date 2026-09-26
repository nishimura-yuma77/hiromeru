"use client";

import type { FormEvent } from "react";
import Link from "next/link";

import type {
  CampaignListItem,
  CampaignListResponse,
  MetricsSummary,
} from "@/features/campaigns/types/campaign";
import {
  campaignPageHref,
  parsePositiveId,
  type CampaignListParams,
} from "@/features/campaigns/utils/campaignParams";

import styles from "./CampaignList.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const rateFormat = new Intl.NumberFormat("ja-JP", {
  style: "percent",
  maximumFractionDigits: 1,
});
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "日時不明" : dateFormat.format(date);
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

function CampaignCards({ campaigns }: { campaigns: CampaignListItem[] }) {
  return (
    <div className={styles.mobileCards}>
      {campaigns.map((campaign) => (
        <article className={styles.card} key={campaign.id}>
          <div className={styles.cardMain}>
            <div className={styles.recordLine}>
              <p className={styles.recordId}>施策ID {campaign.id}</p>
              {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
            </div>
            <h3>{campaign.title}</h3>
            <p className={styles.objective}>{campaign.objective}</p>
          </div>
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
        <thead>
          <tr>
            <th scope="col">施策</th>
            <th scope="col">公開済み</th>
            <th scope="col">初週PV</th>
            <th scope="col">流入ユーザー</th>
            <th scope="col">流入率</th>
            <th scope="col">計測状況</th>
            <th scope="col">更新</th>
          </tr>
        </thead>
        <tbody>
          {campaigns.map((campaign) => {
            const summary = campaign.metrics_summary;
            const explanation = metricExplanation(summary);
            return (
              <tr key={campaign.id}>
                <th scope="row">
                  <span className={styles.tableId}>ID {campaign.id}</span>
                  {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
                  <Link href={`/campaigns/${campaign.id}`}>{campaign.title}</Link>
                  <span className={styles.tableObjective}>{campaign.objective}</span>
                </th>
                <td>{numberFormat.format(summary.post_count)}件</td>
                <td>{metricValue(summary, summary.x_pv_count)}</td>
                <td>{metricValue(summary, summary.landing_user_count)}</td>
                <td>{rateValue(summary)}</td>
                <td>
                  {explanation ? <span className={styles.metricExplanation}>{explanation}</span> : null}
                  <StatusBadges summary={summary} />
                </td>
                <td><time dateTime={campaign.updated_at}>{formatDate(campaign.updated_at)}</time></td>
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

export function CampaignList({ response, params }: CampaignListProps) {
  const hasAdvancedFilters = Boolean(
    params.archived !== "all" || params.createdFrom || params.createdTo,
  );
  const hasFilters = Boolean(
    params.query || hasAdvancedFilters,
  );

  function validateDateRange(event: FormEvent<HTMLFormElement>) {
    const form = event.currentTarget;
    const from = form.elements.namedItem("created_from") as HTMLInputElement;
    const to = form.elements.namedItem("created_to") as HTMLInputElement;
    from.setCustomValidity("");
    to.setCustomValidity("");
    if (from.value && to.value && from.value > to.value) {
      event.preventDefault();
      to.setCustomValidity("終了日は開始日以降の日付を指定してください。");
      to.reportValidity();
    }
  }

  function validateDirectId(event: FormEvent<HTMLFormElement>) {
    const input = event.currentTarget.elements.namedItem("id") as HTMLInputElement;
    input.setCustomValidity("");
    if (parsePositiveId(input.value.trim()) === null) {
      event.preventDefault();
      input.setCustomValidity("施策IDは1以上の整数で入力してください。");
      input.reportValidity();
    }
  }

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Campaign archive</p>
          <h1>施策</h1>
          <p>採用施策と、その後の投稿・成果を一緒に振り返れます。</p>
        </div>
        <Link className={styles.primaryLink} href="/chat/new">新しい施策を作る</Link>
      </header>

      <section className={styles.filters} aria-labelledby="campaign-search-title">
        <h2 id="campaign-search-title">施策を探す</h2>
        <form action="/campaigns" method="get" className={styles.filterForm} onSubmit={validateDateRange}>
          <label className={styles.searchField}>
            <span>施策を検索</span>
            <input
              type="search"
              name="query"
              defaultValue={params.query}
              maxLength={1000}
              placeholder="タイトル、ターゲット、背景、目的、施策内容を検索"
            />
          </label>
          <details className={styles.advancedFilters}>
            <summary>詳細条件{hasAdvancedFilters ? "（適用中）" : ""}</summary>
            <div className={styles.advancedFields}>
              <label>
                <span>状態</span>
                <select name="archived" defaultValue={params.archived}>
                  <option value="all">すべて</option>
                  <option value="active">進行中</option>
                  <option value="archived">アーカイブ済み</option>
                </select>
              </label>
              <label>
                <span>作成日の開始</span>
                <input type="date" name="created_from" defaultValue={params.createdFrom} />
              </label>
              <label>
                <span>作成日の終了</span>
                <input type="date" name="created_to" defaultValue={params.createdTo} />
              </label>
            </div>
          </details>
          <div className={styles.filterActions}>
            <button type="submit">条件を適用</button>
            <Link href="/campaigns">条件をクリア</Link>
          </div>
        </form>
        <form action="/campaigns/open" method="get" className={styles.idForm} onSubmit={validateDirectId}>
          <label>
            <span>施策IDで直接開く</span>
            <input type="text" name="id" inputMode="numeric" pattern="[1-9][0-9]*" required />
          </label>
          <button type="submit">開く</button>
        </form>
      </section>

      <section aria-labelledby="campaign-results-title">
        <div className={styles.resultHeading}>
          <div>
            <p className={styles.eyebrow}>Results</p>
            <h2 id="campaign-results-title">
              {params.query ? `「${params.query}」に近い施策` : "施策一覧"}
            </h2>
          </div>
          {params.query ? <p>施策の内容をもとに関連度順で表示しています。</p> : null}
        </div>

        {response.campaigns.length === 0 ? (
          <div className={styles.empty}>
            <h3>{hasFilters ? "条件に合う施策がありません" : "まだ施策がありません"}</h3>
            <p>{hasFilters ? "検索語や作成日の範囲を変更してください。" : "Hiromeru AIと相談して、最初の施策を作成しましょう。"}</p>
            <Link href={hasFilters ? "/campaigns" : "/chat/new"}>{hasFilters ? "検索条件をクリア" : "新しい施策を作る"}</Link>
          </div>
        ) : (
          <>
            <CampaignTable campaigns={response.campaigns} />
            <CampaignCards campaigns={response.campaigns} />
          </>
        )}

        {!params.query && (params.cursor || response.next_cursor) ? (
          <nav className={styles.pagination} aria-label="施策一覧のページ移動">
            {params.cursor ? <Link href={campaignPageHref(params)}>先頭へ</Link> : null}
            {response.next_cursor ? <Link href={campaignPageHref(params, response.next_cursor)}>次の20件</Link> : null}
          </nav>
        ) : null}
      </section>
    </main>
  );
}
