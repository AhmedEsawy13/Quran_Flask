import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderWorkspace } from "@/components/reader-workspace";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مصحف أثَر بوضعي الصفحة والآية وطبعات المدينة المتعددة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main id="athar-main" className="reader-main shell-width" tabIndex={-1}>
      <header className="reader-intro">
        <p className="eyebrow">المصحف — القراءة الهادئة</p>
        <h1>اقرأ المصحــف، ودع الأدوات تأتي إليك.</h1>
        <p>
          تنقّل بالرسم صفحةً كاملة أو آيةً مركّزة، واختر طبعة المدينة التي ترتاح
          لها. موضعك محفوظ والرابط يعيدك إلى القراءة نفسها.
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
        <ReaderWorkspace />
      </Suspense>
    </main>
  );
}
