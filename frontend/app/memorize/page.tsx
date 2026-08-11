import type { Metadata } from "next";
import { Suspense } from "react";
import { MemorizeWorkspace } from "@/components/memorize-workspace";
import { PageHeader } from "@/components/ui/primitives";

export const metadata: Metadata = {
  title: "تثبيت",
  description: "جلسة تثبيت الحفظ بالتكرار الموقّت على صفحة المصحف.",
  alternates: { canonical: "/memorize" },
};

export default function MemorizePage() {
  return (
    <main id="athar-main" className="shell-width py-8 pb-24 sm:py-10 md:py-14 md:pb-28" tabIndex={-1}>
      <PageHeader
        eyebrow="تثبيت — من النظر إلى الاستحضار"
        title="كرّر، أخفِ، ثم استحضر."
        description="اختر نطاقك، ودع التلاوة تنتقل كلمةً كلمة وآيةً آية على صفحة المصحف نفسها. الرابط يحفظ النطاق لتعود إلى الجلسة مباشرة."
      />
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
