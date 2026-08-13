import type { Metadata } from "next";
import { Suspense } from "react";
import { ReaderWorkspace } from "@/components/reader-workspace";
import { RouteSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = {
  title: "المصحف",
  description: "مصحف أثَر بوضعي الصفحة والآية، مع رسوم المدينة والأزهر والشمرلي ودليل مبسّط لعلامات الوقف والتلاوة.",
  alternates: { canonical: "/read" },
};

export default function ReaderPage() {
  return (
    <main
      id="athar-main"
      className="mx-auto h-[calc(100svh-var(--bar-height)-4.5rem)] w-full max-w-[1600px] overflow-hidden px-2 py-2 md:h-[calc(100svh-var(--bar-height))] md:px-3"
      tabIndex={-1}
    >
      <h1 className="sr-only">المصحف</h1>
      <Suspense
        fallback={<RouteSkeleton label="جارٍ تجهيز المصحف" />}
      >
        <ReaderWorkspace />
      </Suspense>
    </main>
  );
}
