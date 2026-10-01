import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
