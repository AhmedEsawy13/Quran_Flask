import type { NextConfig } from "next";

function requiredOrigin(name: string, fallback: string) {
  const value = process.env[name];
  if (process.env.VERCEL && !value) {
    throw new Error(`${name} must be set on Vercel so production does not fall back to localhost.`);
  }
  return (value || fallback).replace(/\/$/, "");
}

const apiOrigin = requiredOrigin("ATHAR_API_ORIGIN", "http://127.0.0.1:5001");
if (process.env.VERCEL) {
  requiredOrigin("NEXT_PUBLIC_LEGACY_APP_ORIGIN", "http://127.0.0.1:5001");
  requiredOrigin("NEXT_PUBLIC_SITE_URL", "http://localhost:3000");
}

const nextConfig: NextConfig = {
  poweredByHeader: false,
  reactStrictMode: true,
  turbopack: {
    root: process.cwd(),
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: "/api/tawjih/media/:tweetId",
          destination: `${apiOrigin}/api/tawjih/media/:tweetId`,
        },
        {
          source: "/backend-api/:path*",
          destination: `${apiOrigin}/api/:path*`,
        },
        {
          source: "/backend-fonts/:path*",
          destination: `${apiOrigin}/static/fonts/:path*`,
        },
      ],
      afterFiles: [],
      fallback: [],
    };
  },
  async headers() {
    return [
      {
        source: "/fonts/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        source: "/backend-fonts/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
