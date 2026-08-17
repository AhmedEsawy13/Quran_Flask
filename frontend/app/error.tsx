"use client";

import Link from "next/link";
import {Button} from "@/components/ui/primitives";
import {actionLinkClassName, pageContainerClassName} from "@/lib/ui";

export default function AppError({reset}: {error: Error & {digest?: string}; reset: () => void}) {
  return (
    <main
      id="athar-main"
      className={`${pageContainerClassName} grid min-h-[calc(100dvh-var(--bar-height)-4.5rem)] place-items-center py-12 md:min-h-[calc(100dvh-var(--bar-height))]`}
      tabIndex={-1}
    >
      <section className="grid max-w-xl gap-5 rounded-athar-lg border border-athar-line bg-athar-surface p-7 text-center shadow-athar-sm">
        <p className="m-0 text-sm font-bold text-athar-gold">تعذّر إكمال الصفحة</p>
        <h1 className="m-0 font-athar-display text-4xl text-athar-ink">حدث خطأ غير متوقّع.</h1>
        <p className="m-0 leading-7 text-athar-ink-soft">
          جرّب تحميل الصفحة مرة أخرى. إن استمر الخطأ، ارجع إلى الصفحة الرئيسية واختر الباب من جديد.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="primary" onClick={reset}>أعد المحاولة</Button>
          <Link className={actionLinkClassName("quiet")} href="/">الصفحة الرئيسية</Link>
        </div>
      </section>
    </main>
  );
}
