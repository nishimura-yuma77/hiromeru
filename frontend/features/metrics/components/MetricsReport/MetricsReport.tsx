import Link from "next/link";

import type { CampaignMetrics, MetricsReportResponse, MetricsSummary } from "@/features/metrics/types/metrics";
import { metricsPageHref, type MetricsParams } from "@/features/metrics/utils/metricsParams";
import { MetricBar } from "@/shared/components/MetricBar/MetricBar";

import styles from "./MetricsReport.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const percentFormat = new Intl.NumberFormat("ja-JP", {
  style: "percent",
  maximumFractionDigits: 1,
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
        aria-label={compact ? undefined : `${campaign.title}の投稿を見る`}
      >
        {compact ? "この施策の投稿を見る" : "見る"}
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
  const scaleMax = Math.max(1, Math.ceil(Math.max(0, ...rates)));
  const summaryReason = rateUnavailableReason(report.summary);
  const excluded = exclusionNote(report.summary);
  const graphEmpty = rates.length === 0;

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Performance report</p>
        <h1>計測結果</h1>
        <p>公開済み投稿の初週成果を、全体と施策ごとに比較できます。</p>
      </header>

      <section className={styles.filters} aria-labelledby="metrics-period-title">
        <h2 id="metrics-period-title">集計期間</h2>
        <form action="/metrics" method="get">
          <label><span>開始</span><input type="date" name="published_from" defaultValue={params.publishedFrom} /></label>
          <label><span>終了</span><input type="date" name="published_to" defaultValue={params.publishedTo} /></label>
          <button type="submit">期間を適用</button>
          {params.publishedFrom || params.publishedTo ? <Link href="/metrics">全期間に戻す</Link> : <span className={styles.disabledAction}>全期間に戻す</span>}
        </form>
        <p>終了日はその日を含みます。日付は日本時間で集計します。</p>
      </section>

      <p className={styles.period}>集計期間: {periodLabel(params)}</p>

      <section className={styles.summary} aria-labelledby="overall-metrics-title">
        <h2 id="overall-metrics-title" className={styles.visuallyHidden}>全体集計</h2>
        <div className={styles.rateCard}>
          <p>全体の流入率</p>
          <strong>{formatRate(report.summary)}</strong>
          {summaryReason ? <p className={styles.rateReason}>{summaryReason}</p> : (
            <p>流入ユーザー {numberFormat.format(report.summary.landing_user_count)} ÷ 初週PV {numberFormat.format(report.summary.x_pv_count)}</p>
          )}
          <p>計測済み投稿だけで算出</p>
        </div>
        <dl className={styles.summaryMetrics}>
          <div><dt>初週PV</dt><dd>{numberFormat.format(report.summary.x_pv_count)}</dd><p>計測済み投稿の合計</p></div>
          <div><dt>流入ユーザー</dt><dd>{numberFormat.format(report.summary.landing_user_count)}</dd><p>計測済み投稿の合計</p></div>
        </dl>
      </section>

      <div className={styles.overallStatus}>
        <p>公開済み投稿 {numberFormat.format(report.summary.post_count)}件 <StatusBadges summary={report.summary} /></p>
        {excluded ? <p>{excluded}</p> : null}
        {report.summary.post_count === 0 ? <p>公開済み投稿がないため、計測結果はありません。</p> : null}
      </div>

      <section className={styles.graph} aria-labelledby="campaign-graph-title">
        <div className={styles.sectionHeading}>
          <div><p className={styles.eyebrow}>By campaign</p><h2 id="campaign-graph-title">施策別の流入率</h2></div>
          <p>初週PVの多い順</p>
        </div>
        <p>流入ユーザー数 ÷ 初週PV数。計測済み投稿だけで集計</p>
        {report.campaigns.length > 0 && !graphEmpty ? (
          <>
            <div className={styles.scale} aria-hidden="true"><span>0%</span><span>{scaleMax}%</span></div>
            <ul className={styles.graphList}>
              {report.campaigns.map((campaign) => {
                const reason = rateUnavailableReason(campaign);
                return (
                  <li key={campaign.id}>
                    <div className={styles.graphTitle}><span>{campaign.title}</span><strong>{formatRate(campaign)}</strong></div>
                    {campaign.landing_rate === null ? null : <MetricBar value={campaign.landing_rate * 100} max={scaleMax} />}
                    {reason ? <p className={styles.rateReason}>{reason}</p> : null}
                    <p>初週PV {numberFormat.format(campaign.x_pv_count)} ・ 流入ユーザー {numberFormat.format(campaign.landing_user_count)} ・ 計測済み {numberFormat.format(campaign.completed_count)}/{numberFormat.format(campaign.post_count)}件</p>
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
        <h2 id="campaign-metrics-title">施策ごとの詳細</h2>
        {report.campaigns.length === 0 ? (
          <div className={styles.empty}><h3>対象期間の投稿がありません</h3><p>期間を変更するか、投稿を公開してから確認してください。</p></div>
        ) : (
          <>
            <div className={styles.desktopTable}>
              <table>
                <caption>施策ごとの計測結果</caption>
                <thead><tr><th scope="col">施策</th><th scope="col">計測状況</th><th scope="col">初週PV</th><th scope="col">流入</th><th scope="col">流入率</th><th scope="col">投稿</th></tr></thead>
                <tbody>
                  {report.campaigns.map((campaign) => (
                    <tr key={campaign.id}>
                      <th scope="row"><CampaignName campaign={campaign} params={params} /></th>
                      <td><span>公開済み {numberFormat.format(campaign.post_count)}件</span><StatusBadges summary={campaign} /></td>
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
    </main>
  );
}
