import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    // 招待画面のURLはトークンを含むため、RefererとCacheに残さない（SCREEN_DESIGN SC-12）。
    return [
      {
        source: "/invitations/accept",
        headers: [
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "Cache-Control", value: "no-store" },
        ],
      },
    ];
  },
  async rewrites() {
    if (!process.env.FASTAPI_URL) {
      return [];
    }

    return [
      {
        source: "/api/:path*",
        destination: `${process.env.FASTAPI_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
