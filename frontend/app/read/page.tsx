import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderPilot } from "@/components/reader-pilot";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مسار أثَر التجريبي لقراءة القرآن بواجهة Next.js سريعة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main id="athar-main" className="reader-main shell-width" tabIndex={-1}>
      <header className="reader-intro">
        <p className="eyebrow">المصحف — مسار الأداء التجريبي</p>
        <h1>اقرأ المصحــف، ودع الأدوات تأتي إليك.</h1>
        <p>
          الهيكل والخط يظهران أولًا من Vercel؛ نص الآية يصل من واجهة Python الحالية
          دون تحميل التطبيق القديم كله.
        </p>
      </header>
      <Suspense
        fallback={
          <div className="reader-route-skeleton" aria-label="جارٍ تجهيز المصحف">
            <span />
            <span />
          </div>
        }
      >
        <ReaderPilot />
      </Suspense>
    </main>
  );
}
