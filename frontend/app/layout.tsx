import type { Metadata, Viewport } from "next";

import "@/shared/styles/globals.scss";

export const metadata: Metadata = {
  title: "Hiromeru | 前回の結果から、次の採用施策を考える",
  description:
    "採用Xの企画、投稿、承認、計測をひとつの運用記録につなぎ、次の施策で使える知見に変えるAIエージェント。",
};

export const viewport: Viewport = {
  colorScheme: "light",
  themeColor: "#f7f9f8",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
