import type {MetadataRoute} from "next";

const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/backend-api/", "/backend-fonts/"],
    },
    sitemap: `${siteUrl}/sitemap.xml`,
  };
}
