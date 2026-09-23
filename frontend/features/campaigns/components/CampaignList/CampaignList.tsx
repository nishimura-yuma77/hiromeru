import Link from "next/link";

import type { CampaignListResponse } from "@/features/campaigns/types/campaign";
import {
  campaignPageHref,
  type CampaignListParams,
} from "@/features/campaigns/utils/campaignParams";

import styles from "./CampaignList.module.scss";

const numberFormat = new Intl.NumberFormat("ja-JP");
const dateFormat = new Intl.DateTimeFormat("ja-JP", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Tokyo",
});

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "日時不明" : dateFormat.format(date);
}

function formatRate(value: number | null): string {
  return value === null
    ? "—"
    : new Intl.NumberFormat("ja-JP", { style: "percent", maximumFractionDigits: 1 }).format(value);
}

type CampaignListProps = {
  response: CampaignListResponse;
  params: CampaignListParams;
};

export function CampaignList({ response, params }: CampaignListProps) {
  const hasFilters = Boolean(
    params.query || params.archived !== "all" || params.createdFrom || params.createdTo,
  );

  return (
    <main id="main-content" className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Campaign archive</p>
          <h1>施策</h1>
          <p>採用施策と、その後の投稿・成果を一緒に振り返れます。</p>
        </div>
        <Link className={styles.primaryLink} href="/chat/new">
          新しい施策を作る
        </Link>
      </header>

      <section className={styles.filters} aria-labelledby="campaign-search-title">
        <h2 id="campaign-search-title">施策を探す</h2>
        <form action="/campaigns" method="get" className={styles.filterForm}>
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
          <div className={styles.filterActions}>
            <button type="submit">条件を適用</button>
            <Link href="/campaigns">条件をクリア</Link>
          </div>
        </form>
        <form action="/campaigns/open" method="get" className={styles.idForm}>
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
            <p>
              {hasFilters
                ? "検索語や作成日の範囲を変更してください。"
                : "Hiromeru AIと相談して、最初の施策を作成しましょう。"}
            </p>
            <Link href={hasFilters ? "/campaigns" : "/chat/new"}>
              {hasFilters ? "検索条件をクリア" : "新しい施策を作る"}
            </Link>
          </div>
        ) : (
          <div className={styles.list}>
            {response.campaigns.map((campaign) => (
              <article className={styles.card} key={campaign.id}>
                <div className={styles.cardMain}>
                  <p className={styles.recordId}>施策ID {campaign.id}</p>
                  {campaign.archived_at ? <span className={styles.archivedBadge}>アーカイブ済み</span> : null}
                  <h3>{campaign.title}</h3>
                  <p className={styles.objective}>{campaign.objective}</p>
                  <Link href={`/campaigns/${campaign.id}`}>詳細を見る</Link>
                </div>
                <dl className={styles.metrics}>
                  <div>
                    <dt>公開済み</dt>
                    <dd>{numberFormat.format(campaign.metrics_summary.post_count)}件</dd>
                  </div>
                  <div>
                    <dt>初週PV</dt>
                    <dd>{numberFormat.format(campaign.metrics_summary.x_pv_count)}</dd>
                  </div>
                  <div>
                    <dt>流入ユーザー</dt>
                    <dd>{numberFormat.format(campaign.metrics_summary.landing_user_count)}</dd>
                  </div>
                  <div>
                    <dt>流入率</dt>
                    <dd>{formatRate(campaign.metrics_summary.landing_rate)}</dd>
                  </div>
                </dl>
                <div className={styles.statuses} aria-label="計測状況">
                  <span>計測済み {campaign.metrics_summary.completed_count}</span>
                  <span>待ち {campaign.metrics_summary.pending_count}</span>
                  <span>失敗 {campaign.metrics_summary.failed_count}</span>
                </div>
                <p className={styles.dates}>
                  <time dateTime={campaign.created_at}>作成 {formatDate(campaign.created_at)}</time>
                  <time dateTime={campaign.updated_at}>更新 {formatDate(campaign.updated_at)}</time>
                </p>
              </article>
            ))}
          </div>
        )}

        {!params.query && (params.cursor || response.next_cursor) ? (
          <nav className={styles.pagination} aria-label="施策一覧のページ移動">
            {params.cursor ? <Link href={campaignPageHref(params)}>先頭へ</Link> : null}
            {response.next_cursor ? (
              <Link href={campaignPageHref(params, response.next_cursor)}>次の20件</Link>
            ) : null}
          </nav>
        ) : null}
      </section>
    </main>
  );
}
