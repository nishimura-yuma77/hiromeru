import Link from "next/link";
import { Input } from "@/shared/components/Input/Input";

import type { CampaignMetrics, MetricsReportResponse, MetricsSummary } from "@/features/metrics/types/metrics";
import { metricsPageHref, type MetricsParams } from "@/features/metrics/utils/metricsParams";
import { MetricBar } from "@/shared/components/MetricBar/MetricBar";

import styles from "./MetricsReport.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const percentFormat = new Intl.NumberFormat("ja-JP", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatRate(summary: MetricsSummary): string {
  return summary.landing_rate === null ? "—" : percentFormat.format(summary.landing_rate);
}

function rateUnavailableReason(summary: MetricsSummary): string | null {
  if (summary.landing_rate !== null) return null;
  return summary.completed_count === 0
    ? "計測済みの投稿がありません"
    : "初週PVが0のため流入率を算出できません";
}

function StatusBadges({ summary }: { summary: MetricsSummary }) {
  const statuses = [
    ["計測済み", summary.completed_count, styles.completedBadge],
    ["計測待ち", summary.pending_count, styles.pendingBadge],
    ["計測失敗", summary.failed_count, styles.failedBadge],
  ] as const;
  return (
    <span className={styles.statusBadges}>
      {statuses.map(([label, count, className]) => count > 0 ? (
        <span className={className} key={label}>{label} {numberFormat.format(count)}</span>
      ) : null)}
    </span>
  );
}

function exclusionNote(summary: MetricsSummary): string | null {
  const excluded = [];
  if (summary.pending_count > 0) excluded.push(`計測待ち${numberFormat.format(summary.pending_count)}件`);
  if (summary.failed_count > 0) excluded.push(`失敗${numberFormat.format(summary.failed_count)}件`);
  return excluded.length
    ? `初週PV・流入ユーザー・流入率には${excluded.join("、")}を含みません。`
    : null;
}

function periodLabel(params: MetricsParams): string {
  if (params.publishedFrom && params.publishedTo) return `${params.publishedFrom}〜${params.publishedTo}`;
  if (params.publishedFrom) return `${params.publishedFrom}以降`;
  if (params.publishedTo) return `${params.publishedTo}まで`;
  return "全期間";
}

function datedHref(path: string, params: MetricsParams, campaignId?: number): string {
  const query = new URLSearchParams();
  if (campaignId) query.set("campaign_id", String(campaignId));
  if (params.publishedFrom) query.set("published_from", params.publishedFrom);
  if (params.publishedTo) query.set("published_to", params.publishedTo);
  const value = query.toString();
  return value ? `${path}?${value}` : path;
}

function CampaignLinks({ campaign, params, compact = false }: { campaign: CampaignMetrics; params: MetricsParams; compact?: boolean }) {
  return (
    <div className={styles.campaignLinks}>
      {compact ? <Link href={datedHref(`/campaigns/${campaign.id}`, params)}>施策を見る</Link> : null}
      <Link
        href={datedHref("/posts", params, campaign.id)}
        aria-label={compact ? undefined : `${campaign.title}の投稿を見る（${numberFormat.format(campaign.post_count)}件）`}
      >
        {compact ? "この施策の投稿を見る" : numberFormat.format(campaign.post_count)}
      </Link>
    </div>
  );
}

function CampaignName({ campaign, params, linked = true }: { campaign: CampaignMetrics; params: MetricsParams; linked?: boolean }) {
  return (
    <div className={styles.campaignName}>
      {linked ? <Link href={datedHref(`/campaigns/${campaign.id}`, params)}>{campaign.title}</Link> : <h3>{campaign.title}</h3>}
      {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
    </div>
  );
}

export function MetricsReport({ report, params }: { report: MetricsReportResponse; params: MetricsParams }) {
  const rates = report.campaigns.flatMap((campaign) => campaign.landing_rate === null ? [] : [campaign.landing_rate * 100]);
  const scaleMax = Math.max(0, ...rates);
  const summaryReason = rateUnavailableReason(report.summary);
  const excluded = exclusionNote(report.summary);
  const graphEmpty = rates.length === 0;

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <h1>計測結果</h1>
        <form action="/metrics" method="get" className={styles.periodForm} aria-label="集計期間">
          <label><span>開始日</span><Input type="date" name="published_from" defaultValue={params.publishedFrom} /></label>
          <span className={styles.periodSeparator} aria-hidden="true">〜</span>
          <label><span>終了日</span><Input type="date" name="published_to" defaultValue={params.publishedTo} /></label>
          <button type="submit">適用</button>
          {params.publishedFrom || params.publishedTo ? <Link href="/metrics">全期間</Link> : <span className={styles.disabledAction}>全期間</span>}
        </form>
      </header>

      <div className={styles.body}>
      <p className={styles.period}>集計期間: {periodLabel(params)} <span>（日本時間・終了日を含む）</span></p>

      <section className={styles.summary} aria-labelledby="overall-metrics-title">
        <h2 id="overall-metrics-title" className={styles.visuallyHidden}>全体集計</h2>
        <div className={styles.rateCard}>
          <p>全体流入率</p>
          <strong>{report.summary.landing_rate === null ? "—" : <>{formatRate(report.summary).replace(/%$/, "")}<span>%</span></>}</strong>
          {summaryReason ? <p className={styles.rateReason}>{summaryReason}</p> : (
            <p>{numberFormat.format(report.summary.x_pv_count)} PV に対して {numberFormat.format(report.summary.landing_user_count)} ユーザーが流入</p>
          )}
        </div>
        <dl className={styles.summaryMetrics}>
          <div><dt>初週PV合計</dt><dd>{numberFormat.format(report.summary.x_pv_count)}</dd></div>
          <div><dt>流入ユーザー合計</dt><dd>{numberFormat.format(report.summary.landing_user_count)}</dd></div>
          <div><dt>計測済み投稿</dt><dd>{numberFormat.format(report.summary.completed_count)}件</dd><p>全{numberFormat.format(report.summary.post_count)}件中</p></div>
          <div className={styles.statusCard}><dt>計測状態</dt><dd>
            <span><i className={styles.completedDot} aria-hidden="true" />計測済み <strong>{numberFormat.format(report.summary.completed_count)}</strong></span>
            <span><i className={styles.pendingDot} aria-hidden="true" />計測待ち <strong>{numberFormat.format(report.summary.pending_count)}</strong></span>
            <span><i className={styles.failedDot} aria-hidden="true" />計測失敗 <strong>{numberFormat.format(report.summary.failed_count)}</strong></span>
          </dd></div>
        </dl>
      </section>

      <div className={styles.overallStatus}>
        {excluded ? <p>{excluded}</p> : null}
        {report.summary.post_count === 0 ? <p>公開済み投稿がないため、計測結果はありません。</p> : null}
      </div>

      <section className={styles.graph} aria-labelledby="campaign-graph-title">
        <div className={styles.sectionHeading}>
          <h2 id="campaign-graph-title">施策別流入率比較</h2>
        </div>
        {report.campaigns.length > 0 && !graphEmpty ? (
          <>
            <ul className={styles.graphList}>
              {report.campaigns.map((campaign) => {
                const reason = rateUnavailableReason(campaign);
                return (
                  <li key={campaign.id}>
                    <div className={styles.graphContent}>
                      <span className={styles.graphTitle}>{campaign.title}</span>
                      <MetricBar value={(campaign.landing_rate ?? 0) * 100} max={scaleMax} />
                      {reason ? <p className={styles.rateReason}>{reason}</p> : null}
                    </div>
                    <div className={styles.graphValues}><strong>{formatRate(campaign)}</strong><span>{numberFormat.format(campaign.x_pv_count)} PV</span></div>
                  </li>
                );
              })}
            </ul>
          </>
        ) : report.campaigns.length > 0 ? (
          <p className={styles.comparisonUnavailable}>{report.campaigns.some((campaign) => campaign.completed_count > 0) ? "初週PVが0のため比較できる流入率がありません" : "比較できる計測結果がありません"}</p>
        ) : null}
      </section>

      <section className={styles.campaigns} aria-labelledby="campaign-metrics-title">
        <h2 id="campaign-metrics-title">施策別詳細</h2>
        {report.campaigns.length === 0 ? (
          <div className={styles.empty}><h3>対象期間の投稿がありません</h3><p>期間を変更するか、投稿を公開してから確認してください。</p></div>
        ) : (
          <>
            <div className={styles.desktopTable}>
              <table>
                <caption>施策ごとの計測結果</caption>
                <thead><tr><th scope="col">施策</th><th scope="col">PV</th><th scope="col">流入</th><th scope="col">流入率</th><th scope="col">投稿数</th></tr></thead>
                <tbody>
                  {report.campaigns.map((campaign) => (
                    <tr key={campaign.id}>
                      <th scope="row"><CampaignName campaign={campaign} params={params} /><span className={styles.campaignId}>施策ID {campaign.id}</span><StatusBadges summary={campaign} /></th>
                      <td>{numberFormat.format(campaign.x_pv_count)}</td>
                      <td>{numberFormat.format(campaign.landing_user_count)}</td>
                      <td><strong>{formatRate(campaign)}</strong>{rateUnavailableReason(campaign) ? <small>{rateUnavailableReason(campaign)}</small> : null}</td>
                      <td><CampaignLinks campaign={campaign} params={params} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={styles.mobileCards}>
              {report.campaigns.map((campaign) => (
                <article key={campaign.id} className={styles.campaignCard}>
                  <CampaignName campaign={campaign} params={params} linked={false} />
                  <p>公開済み投稿 <strong>{numberFormat.format(campaign.post_count)}件</strong></p>
                  <StatusBadges summary={campaign} />
                  <dl>
                    <div><dt>初週PV</dt><dd>{numberFormat.format(campaign.x_pv_count)}</dd></div>
                    <div><dt>流入ユーザー</dt><dd>{numberFormat.format(campaign.landing_user_count)}</dd></div>
                    <div><dt>流入率</dt><dd>{formatRate(campaign)}</dd></div>
                  </dl>
                  {rateUnavailableReason(campaign) ? <p className={styles.rateReason}>{rateUnavailableReason(campaign)}</p> : null}
                  <CampaignLinks campaign={campaign} params={params} compact />
                </article>
              ))}
            </div>
          </>
        )}
        {params.cursor || report.next_cursor ? (
          <nav className={styles.pagination} aria-label="施策別集計のページ移動">
            {params.cursor ? <Link href={metricsPageHref(params)}>先頭へ</Link> : null}
            {report.next_cursor ? <Link href={metricsPageHref(params, report.next_cursor)}>次の20件</Link> : null}
          </nav>
        ) : null}
      </section>
      </div>
    </main>
  );
}
