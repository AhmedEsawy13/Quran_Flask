const fallbackLegacyOrigin = "http://127.0.0.1:5001";

export function legacyUrl(path: string): string {
  const origin = (
    process.env.NEXT_PUBLIC_LEGACY_APP_ORIGIN || fallbackLegacyOrigin
  ).replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${origin}${normalizedPath}`;
}

export function backendMediaUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  return url.startsWith("/api/") ? `/backend-api/${url.slice(5)}` : url;
}
