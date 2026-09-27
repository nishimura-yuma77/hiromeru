import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  distDir: process.env.NODE_ENV === "production" ? ".next-production" : ".next",
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
