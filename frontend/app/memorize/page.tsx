import type { Metadata } from "next";
import { Suspense } from "react";
import { MemorizeWorkspace } from "@/components/memorize-workspace";
import { RouteSkeleton } from "@/components/ui/primitives";

export const metadata: Metadata = {
  title: "تثبيت",
  description: "جلسة تثبيت الحفظ بالتكرار الموقّت على صفحة المصحف.",
  alternates: { canonical: "/memorize" },
};

export default function MemorizePage() {
  return (
    <div id="athar-main" className="h-full" tabIndex={-1}>
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز جلسة التثبيت" />}>
        <MemorizeWorkspace />
      </Suspense>
    </div>
  );
}
