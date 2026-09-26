import type { Metadata, Viewport } from "next";
import { AppShell } from "@/components/app-shell";
import "./globals.css";

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
// Saved choice wins; otherwise follow the OS so dark-mode users never get a light flash.
const themeBootstrap = `try{let t=localStorage.getItem("athar-theme");if(t!=="light"&&t!=="sepia"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t;document.documentElement.style.colorScheme=t==="dark"?"dark":"light"}catch{}`;

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "أثَر · الوقف والابتداء",
    template: "%s · أثَر",
  },
  description:
    "أثَر: مصحف حقيقي، ووقف موثَّق من المطبوع والقرّاء والعلماء — ثم تدريب يقيّمك.",
  applicationName: "أثَر",
  alternates: { canonical: "/" },
  openGraph: {
    locale: "ar_AR",
    siteName: "أثَر",
    type: "website",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f1e2" },
    { media: "(prefers-color-scheme: dark)", color: "#15140d" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{__html: themeBootstrap}} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
