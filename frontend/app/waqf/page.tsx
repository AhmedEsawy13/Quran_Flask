import { Suspense } from "react";
import type { Metadata } from "next";
import { WaqfWorkspace } from "@/components/waqf-workspace";
import { RouteSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = {
  title: "مُكْث",
  description: "قارن علامة المصحف، ووقف القارئ، وقول الإمام، ثم اختر قراءة تناسب نَفَسك.",
  alternates: {canonical: "/waqf"},
};

export default function WaqfPage() {
  return (
    <main id="athar-main" tabIndex={-1}>
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز مُكْث" />}>
        <WaqfWorkspace />
      </Suspense>
    </main>
  );
}
