import type {MetadataRoute} from "next";

const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

const pages: Array<{path: string; changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"]; priority: number}> = [
  {path: "/", changeFrequency: "weekly", priority: 1},
  {path: "/waqf", changeFrequency: "weekly", priority: 0.95},
  {path: "/waqf-practice", changeFrequency: "weekly", priority: 0.9},
  {path: "/read", changeFrequency: "weekly", priority: 0.85},
  {path: "/memorize", changeFrequency: "weekly", priority: 0.8},
  {path: "/credits", changeFrequency: "monthly", priority: 0.4},
];

export default function sitemap(): MetadataRoute.Sitemap {
  return pages.map((page) => ({
    url: `${siteUrl}${page.path === "/" ? "" : page.path}`,
    changeFrequency: page.changeFrequency,
    priority: page.priority,
  }));
}
