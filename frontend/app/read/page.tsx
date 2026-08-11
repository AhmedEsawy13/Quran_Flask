import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderWorkspace } from "@/components/reader-workspace";
import { PageHeader, RouteSkeleton } from "@/components/ui/primitives";
import {cn} from "@/lib/cn";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مصحف أثَر بوضعي الصفحة والآية وطبعات المدينة المتعددة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main id="athar-main" className={cn(pageContainerClassName, "py-8 pb-24 sm:py-10 md:py-14 md:pb-28")} tabIndex={-1}>
      <PageHeader
        eyebrow="المصحف — القراءة الهادئة"
        title="اقرأ المصحــف، ودع الأدوات تأتي إليك."
        description="تنقّل بالرسم صفحةً كاملة أو آيةً مركّزة، واختر طبعة المدينة التي ترتاح لها. موضعك محفوظ والرابط يعيدك إلى القراءة نفسها."
      />
      <Suspense
        fallback={<RouteSkeleton label="جارٍ تجهيز المصحف" />}
      >
        <ReaderWorkspace />
      </Suspense>
    </main>
  );
}
