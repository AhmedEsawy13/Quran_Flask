import Link from "next/link";
import {actionLinkClassName, pageContainerClassName} from "@/lib/ui";

export default function NotFound() {
  return (
    <main
      id="athar-main"
      className={`${pageContainerClassName} grid min-h-[calc(100dvh-var(--bar-height)-4.5rem)] place-items-center py-12 md:min-h-[calc(100dvh-var(--bar-height))]`}
      tabIndex={-1}
    >
      <section className="grid max-w-xl gap-5 rounded-athar-lg border border-athar-line bg-athar-surface p-7 text-center shadow-athar-sm">
        <p className="m-0 text-sm font-bold text-athar-gold">٤٠٤</p>
        <h1 className="m-0 font-athar-display text-4xl text-athar-ink">هذه الصفحة غير موجودة.</h1>
        <p className="m-0 leading-7 text-athar-ink-soft">
          قد يكون الرابط قديمًا أو غير مكتمل. ارجع إلى أبواب أثَر للمتابعة.
        </p>
        <Link className={actionLinkClassName("primary")} href="/">العودة إلى الصفحة الرئيسية</Link>
      </section>
    </main>
  );
}
