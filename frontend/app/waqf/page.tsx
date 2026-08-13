import { Suspense } from "react";
import type { Metadata } from "next";
import { WaqfWorkspace } from "@/components/waqf-workspace";
import { ToolIntro } from "@/components/tool-chrome";
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
      <ToolIntro
        kicker="— مُكْث"
        title="علامة المصحــف، ووقف القارئ، وقول الإمام."
        titleId="wq-title"
        titleAriaLabel="علامة المصحف، ووقف القارئ، وقول الإمام."
        lede="هذا تميّز أثَر: ثلاث شهادات على موضع الوقف — ثم ابنِ قراءةً تناسب نَفَسك."
      >
        <a className={introLinkClassName()} href={legacyUrl("/waqf-lab")}>مختبر الوقف</a>
        <a className={introLinkClassName()} href="/waqf-practice">تدرّب على هذا الموضع</a>
      </ToolIntro>

      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز مُكْث" />}>
        <WaqfWorkspace />
      </Suspense>
    </div>
  );
}
