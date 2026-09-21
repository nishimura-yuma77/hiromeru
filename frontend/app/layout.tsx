import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Hiromeru",
  description: "AI支援型Xマーケティングシステム",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
