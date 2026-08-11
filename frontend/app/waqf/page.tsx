import { Suspense } from "react";
import type { Metadata } from "next";
import { WaqfWorkspace } from "@/components/waqf-workspace";
import { PageHeader, RouteSkeleton } from "@/components/ui/primitives";
import {cn} from "@/lib/cn";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "مُكْث",
  description: "قارن علامة المصحف، ووقف القارئ، وقول الإمام، ثم اختر قراءة تناسب نَفَسك.",
  alternates: {canonical: "/waqf"},
};

export default function WaqfPage() {
  return (
    <main id="athar-main" className={cn(pageContainerClassName, "py-8 pb-24 sm:py-10 md:py-14 md:pb-28")} tabIndex={-1}>
      <PageHeader
        eyebrow="مُكْث — معرفة الوقوف"
        title="علامة المصحف، ووقف القارئ، وقول الإمام."
        description="ثلاث شهادات على الموضع نفسه، ثم قراءة حقيقية من قارئ يناسب سعة نَفَسك."
      />
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز مُكْث" />}>
        <WaqfWorkspace />
      </Suspense>
    </main>
  );
}
