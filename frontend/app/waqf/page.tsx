import { Suspense } from "react";
import type { Metadata } from "next";
import { WaqfWorkspace } from "@/components/waqf-workspace";

export const metadata: Metadata = {
  title: "مُكْث",
  description: "قارن علامة المصحف، ووقف القارئ، وقول الإمام، ثم اختر قراءة تناسب نَفَسك.",
  alternates: {canonical: "/waqf"},
};

export default function WaqfPage() {
  return (
    <main id="athar-main" className="waqf-main shell-width" tabIndex={-1}>
      <header className="waqf-intro">
        <p className="eyebrow">مُكْث — معرفة الوقوف</p>
        <h1>علامة المصحف، ووقف القارئ، وقول الإمام.</h1>
        <p>
          ثلاث شهادات على الموضع نفسه، ثم قراءة حقيقية من قارئ يناسب سعة نَفَسك.
        </p>
      </header>
      <Suspense fallback={<div className="reader-route-skeleton" aria-label="جارٍ تجهيز مُكْث" />}>
        <WaqfWorkspace />
      </Suspense>
    </main>
  );
}
