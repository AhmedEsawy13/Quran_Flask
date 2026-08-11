import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderWorkspace } from "@/components/reader-workspace";
import { RouteSkeleton } from "@/components/ui/primitives";
import {cn} from "@/lib/cn";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مصحف أثَر بوضعي الصفحة والآية، مع رسوم المدينة والأزهر والشمرلي ودليل مبسّط لعلامات الوقف والتلاوة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main id="athar-main" className={cn(pageContainerClassName, "py-2.5 pb-24 sm:py-3 md:pb-20")} tabIndex={-1}>
      <header className="reader-route-header">
        <div>
          <p>المصحف — القراءة الهادئة</p>
          <h1>المصحف</h1>
        </div>
        <span>الصفحة أولًا؛ والتلاوة والفهم حين تحتاجهما.</span>
      </header>
      <Suspense
        fallback={<RouteSkeleton label="جارٍ تجهيز المصحف" />}
      >
        <ReaderWorkspace />
      </Suspense>
    </main>
  );
}
