import Link from "next/link";

import type { MetricsReportResponse, MetricsSummary } from "@/features/metrics/types/metrics";
import { metricsPageHref, type MetricsParams } from "@/features/metrics/utils/metricsParams";

import styles from "./MetricsReport.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const percentFormat = new Intl.NumberFormat("ja-JP", {
  style: "percent",
  maximumFractionDigits: 1,
});

function summaryValues(summary: MetricsSummary) {
  return [
    ["公開済み投稿", `${numberFormat.format(summary.post_count)}件`],
    ["初週PV", numberFormat.format(summary.x_pv_count)],
    ["流入ユーザー", numberFormat.format(summary.landing_user_count)],
    ["流入率", summary.landing_rate === null ? "—" : percentFormat.format(summary.landing_rate)],
  ];
}

export function MetricsReport({ report, params }: { report: MetricsReportResponse; params: MetricsParams }) {
  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Performance report</p>
        <h1>計測結果</h1>
        <p>公開後1週間のPVと、採用ページへの流入を施策ごとに比較できます。</p>
      </header>

      <section className={styles.filters} aria-labelledby="metrics-period-title">
        <h2 id="metrics-period-title">公開期間</h2>
        <form action="/metrics" method="get">
          <label><span>開始</span><input type="date" name="published_from" defaultValue={params.publishedFrom} /></label>
          <label><span>終了</span><input type="date" name="published_to" defaultValue={params.publishedTo} /></label>
          <button type="submit">期間を適用</button>
          <Link href="/metrics">期間をクリア</Link>
        </form>
        <p>終了日はその日を含みます。日付は日本時間で集計します。</p>
      </section>

      <section className={styles.summary} aria-labelledby="overall-metrics-title">
        <div className={styles.sectionHeading}>
          <div><p className={styles.eyebrow}>All campaigns</p><h2 id="overall-metrics-title">全体集計</h2></div>
          <p>計測済み {report.summary.completed_count} / 待ち {report.summary.pending_count} / 失敗 {report.summary.failed_count}</p>
        </div>
        <dl>
          {summaryValues(report.summary).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        {report.summary.pending_count || report.summary.failed_count ? (
          <p className={styles.note}>流入率には計測待ち・失敗の投稿を含みません。</p>
        ) : null}
      </section>

      <section className={styles.campaigns} aria-labelledby="campaign-metrics-title">
        <div className={styles.sectionHeading}>
          <div><p className={styles.eyebrow}>By campaign</p><h2 id="campaign-metrics-title">施策別集計</h2></div>
          <p>初週PVの多い順</p>
        </div>
        {report.campaigns.length === 0 ? (
          <div className={styles.empty}><h3>対象期間の投稿がありません</h3><p>期間を変更するか、投稿を公開してから確認してください。</p></div>
        ) : (
          <div className={styles.list}>
            {report.campaigns.map((campaign, index) => (
              <article key={campaign.id} className={styles.row}>
                <div className={styles.rank} aria-label={`このページの${index + 1}件目`}>PV順</div>
                <div className={styles.campaignTitle}>
                  <h3>{campaign.title}</h3>
                  {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
                  <Link href={`/campaigns/${campaign.id}`}>施策の詳細を見る</Link>
                </div>
                <dl>
                  {summaryValues(campaign).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
                </dl>
                <p>計測済み {campaign.completed_count} / 待ち {campaign.pending_count} / 失敗 {campaign.failed_count}</p>
              </article>
            ))}
          </div>
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
