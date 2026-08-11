import type { Metadata } from "next";
import { Suspense } from "react";
import { MemorizeWorkspace } from "@/components/memorize-workspace";

export const metadata: Metadata = {
  title: "تثبيت",
  description: "جلسة تثبيت الحفظ بالتكرار الموقّت على صفحة المصحف.",
  alternates: { canonical: "/memorize" },
};

export default function MemorizePage() {
  return (
    <main id="athar-main" className="memorize-main shell-width" tabIndex={-1}>
      <header className="memorize-intro">
        <p className="eyebrow">تثبيت — من النظر إلى الاستحضار</p>
        <h1>كرّر، أخفِ، ثم استحضر.</h1>
        <p>
          اختر نطاقك، ودع التلاوة تنتقل كلمةً كلمة وآيةً آية على صفحة المصحف نفسها.
          الرابط يحفظ النطاق لتعود إلى الجلسة مباشرة.
        </p>
      </header>
      <Suspense
        fallback={
          <div className="reader-route-skeleton" aria-label="جارٍ تجهيز جلسة التثبيت">
            <span />
            <span />
          </div>
        }
      >
        <MemorizeWorkspace />
      </Suspense>
    </main>
  );
}
