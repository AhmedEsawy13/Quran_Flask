import type { Metadata } from "next";
import { Suspense } from "react";
import { MemorizeWorkspace } from "@/components/memorize-workspace";
import { PageHeader, RouteSkeleton } from "@/components/ui/primitives";
import {cn} from "@/lib/cn";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "تثبيت",
  description: "جلسة تثبيت الحفظ بالتكرار الموقّت على صفحة المصحف.",
  alternates: { canonical: "/memorize" },
};

export default function MemorizePage() {
  return (
    <main id="athar-main" className={cn(pageContainerClassName, "py-4 pb-24 sm:py-5 md:py-6 md:pb-28")} tabIndex={-1}>
      <PageHeader
        eyebrow="تثبيت — من النظر إلى الاستحضار"
        title="كرّر، أخفِ، ثم استحضر."
        description="اختر نطاقك، ودع التلاوة تنتقل كلمةً كلمة وآيةً آية على صفحة المصحف نفسها. الرابط يحفظ النطاق لتعود إلى الجلسة مباشرة."
        density="utility"
      />
      <Suspense
        fallback={<RouteSkeleton label="جارٍ تجهيز جلسة التثبيت" />}
      >
        <MemorizeWorkspace />
      </Suspense>
    </main>
  );
}
