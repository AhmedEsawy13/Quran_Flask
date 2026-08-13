import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderWorkspace } from "@/components/reader-workspace";
import { RouteSkeleton } from "@/components/ui/primitives";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مصحف أثَر بوضعي الصفحة والآية، مع رسوم المدينة والأزهر والشمرلي ودليل مبسّط لعلامات الوقف والتلاوة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main id="athar-main" className={`${pageContainerClassName} py-2 pb-24 md:pb-20`} tabIndex={-1}>
      <h1 className="sr-only">المصحف</h1>
      <Suspense
        fallback={<RouteSkeleton label="جارٍ تجهيز المصحف" />}
      >
        <ReaderWorkspace />
      </Suspense>
    </main>
  );
}
