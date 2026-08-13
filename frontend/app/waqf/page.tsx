import { Suspense } from "react";
import type { Metadata } from "next";
import { WaqfWorkspace } from "@/components/waqf-workspace";
import { RouteSkeleton } from "@/components/ui/primitives";
import { introLinkClassName } from "@/lib/ui";
import { legacyUrl } from "@/lib/paths";

export const metadata: Metadata = {
  title: "مُكْث",
  description: "قارن علامة المصحف، ووقف القارئ، وقول الإمام، ثم اختر قراءة تناسب نَفَسك.",
  alternates: {canonical: "/waqf"},
};

export default function WaqfPage() {
  return (
    <div id="athar-main" tabIndex={-1}>
      <header className="wq-study-header">
        <p>— مُكْث</p>
        <h1 id="wq-title">علامة المصحف، ووقف القارئ، وقول الإمام.</h1>
        <p className="wq-study-lede">ثلاث شهادات على موضع الوقف — ثم ابنِ قراءةً تناسب نَفَسك، واسمع كل قارئ وقول كل إمام.</p>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          <a className={introLinkClassName()} href={legacyUrl("/waqf-lab")}>مختبر الوقف</a>
          <a className={introLinkClassName()} href="/waqf-practice">تدرّب على هذا الموضع</a>
        </div>
      </header>
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز مُكْث" />}>
        <WaqfWorkspace />
      </Suspense>
    </div>
  );
}
