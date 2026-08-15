import {Suspense} from "react";
import type {Metadata} from "next";
import {WaqfLabWorkspace} from "@/components/waqf-lab-workspace";
import {RouteSkeleton} from "@/components/ui/primitives";

export const metadata: Metadata = {
  title: "مختبر الوقف",
  description: "مختبر الوقف — ابحث في كلمات وأنماط الوقف، وانفرادات القرّاء، واختلاف المصاحف عبر القرآن.",
  alternates: {canonical: "/waqf-lab"},
  robots: {index: false, follow: true},
};

export default function WaqfLabPage() {
  return (
    <div id="athar-main" tabIndex={-1}>
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز مختبر الوقف" />}>
        <WaqfLabWorkspace />
      </Suspense>
    </div>
  );
}
