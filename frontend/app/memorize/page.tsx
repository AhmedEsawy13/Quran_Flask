import type { Metadata } from "next";
import { Suspense } from "react";
import { MemorizeWorkspace } from "@/components/memorize-workspace";
import { ToolIntro } from "@/components/tool-chrome";
import { RouteSkeleton } from "@/components/ui/primitives";
import { introLinkClassName } from "@/lib/ui";
import { legacyUrl } from "@/lib/paths";

export const metadata: Metadata = {
  title: "تثبيت",
  description: "جلسة تثبيت الحفظ بالتكرار الموقّت على صفحة المصحف.",
  alternates: { canonical: "/memorize" },
};

export default function MemorizePage() {
  return (
    <div id="athar-main" tabIndex={-1}>
      <ToolIntro
        kicker="— تثبيت"
        title="ثبّت حفظــك."
        titleId="mz-title"
        titleAriaLabel="ثبّت حفظك."
        lede="كرّر، أخفِ، ثم استحضر. اختر نطاقك، ودع التلاوة تنتقل كلمةً كلمة على صفحة المصحف نفسها."
      >
        <a className={introLinkClassName()} href={legacyUrl("/memorize")}>التسميع الصوتي</a>
      </ToolIntro>
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز جلسة التثبيت" />}>
        <MemorizeWorkspace />
      </Suspense>
    </div>
  );
}
