import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderWorkspace } from "@/components/reader-workspace";
import { PageHeader, RouteSkeleton } from "@/components/ui/primitives";
import {cn} from "@/lib/cn";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مصحف أثَر بوضعي الصفحة والآية، مع رسوم المدينة والأزهر والشمرلي ودليل مبسّط لعلامات الوقف والتلاوة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main id="athar-main" className={cn(pageContainerClassName, "py-5 pb-24 sm:py-6 md:py-8 md:pb-28")} tabIndex={-1}>
      <PageHeader
        eyebrow="المصحف — القراءة الهادئة"
        title="اقرأ المصحــف، ودع الأدوات تأتي إليك."
        description="تنقّل بين صفحة كاملة وآية مركّزة، واختر رسم المدينة أو الأزهر بخط أميري أو الشمرلي حين تتوفر صفحته. مفتاح الصفحة يشرح علامات الوقف، ودليل التلاوة يقسّم الآية بصوت قارئك."
        density="compact"
      />
      <Suspense
        fallback={<RouteSkeleton label="جارٍ تجهيز المصحف" />}
      >
        <ReaderWorkspace />
      </Suspense>
    </main>
  );
}
