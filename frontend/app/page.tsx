"use client";

import { useEffect, useState } from "react";

type CheckState = "checking" | "available" | "unavailable";

type ServiceCheck = {
  label: string;
  detail: string;
  state: CheckState;
};

const initialChecks: ServiceCheck[] = [
  { label: "Next.js", detail: "Frontend", state: "available" },
  { label: "FastAPI", detail: "Vercel Function", state: "checking" },
  { label: "PostgreSQL", detail: "Neon / Local", state: "checking" },
];

async function isAvailable(path: string): Promise<boolean> {
  try {
    const response = await fetch(path, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

export default function Home() {
  const [checks, setChecks] = useState(initialChecks);

  useEffect(() => {
    let active = true;

    async function checkServices() {
      const [apiAvailable, databaseAvailable] = await Promise.all([
        isAvailable("/api/health"),
        isAvailable("/api/health/db"),
      ]);

      if (!active) {
        return;
      }

      setChecks([
        initialChecks[0],
        { ...initialChecks[1], state: apiAvailable ? "available" : "unavailable" },
        {
          ...initialChecks[2],
          state: databaseAvailable ? "available" : "unavailable",
        },
      ]);
    }

    void checkServices();
    return () => {
      active = false;
    };
  }, []);

  return (
    <main>
      <div className="ambient ambientTop" />
      <div className="ambient ambientBottom" />
      <section className="hero">
        <p className="eyebrow">HIROMERU / SYSTEM STATUS</p>
        <h1>
          マーケティングの可能性を、
          <span>もっと遠くへ。</span>
        </h1>
        <p className="lead">
          Next.js、FastAPI、PostgreSQLで構成された開発基盤が稼働しています。
        </p>

        <div className="statusGrid">
          {checks.map((check) => (
            <article className="statusCard" key={check.label}>
              <div>
                <p className="serviceLabel">{check.label}</p>
                <p className="serviceDetail">{check.detail}</p>
              </div>
              <div className={`badge ${check.state}`}>
                <span className="dot" />
                {check.state === "checking"
                  ? "確認中"
                  : check.state === "available"
                    ? "稼働中"
                    : "接続不可"}
              </div>
            </article>
          ))}
        </div>

        <a className="docsLink" href="/api/docs">
          APIドキュメントを開く
          <span aria-hidden="true">↗</span>
        </a>
      </section>
      <footer>HIROMERU · 2026</footer>
    </main>
  );
}
