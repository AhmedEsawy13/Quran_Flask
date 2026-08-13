import Link from "next/link";
import { AyahPreview } from "@/components/ayah-preview";
import {cn} from "@/lib/cn";
import {actionLinkClassName, pageContainerClassName} from "@/lib/ui";

const doors = [
  {
    verb: "اقرأ",
    title: "المصحف",
    description: "رسم مصحفي هادئ، وموضعك محفوظ، وأدواتك تظهر حين تحتاجها.",
    href: "/read?surah=2&ayah=255",
  },
  {
    verb: "تأمّل",
    title: "مُكْث",
    description: "علامة المصحف، ووقف القارئ، وقول الإمام — ثم نفسك وكل القرّاء.",
    href: "/waqf?surah=2&ayah=255",
  },
  {
    verb: "احفظ",
    title: "تثبيت",
    description: "المصحف يملأ الشاشة. كرّر وأخفِ على الصفحة نفسها.",
    href: "/memorize?surah=2&from=255&to=257",
  },
  {
    verb: "تدرّب",
    title: "تدريب",
    description: "علّم مواضع وقوفك، ثم قارنها بالدليل بدل التخمين.",
    href: "/waqf-practice?surah=2&from=255&to=255",
  },
];

export default function HomePage() {
  return (
    <main id="athar-main" tabIndex={-1}>
      <section className={cn(
        pageContainerClassName,
        "grid min-h-[calc(100svh-var(--bar-height))] grid-cols-[minmax(0,.9fr)_minmax(420px,1.1fr)] items-center gap-[clamp(44px,8vw,104px)] py-[70px] max-[920px]:min-h-0 max-[920px]:grid-cols-1 max-[640px]:gap-[46px] max-[640px]:py-[50px_70px]",
      )}>
        <div className="max-[920px]:max-w-[760px]">
          <p className="mb-3 text-[0.78rem] font-bold tracking-[0.08em] text-athar-gold">أثَر — مع القرآن</p>
          <h1 className="m-0 max-w-[660px] font-athar-display text-[clamp(3.5rem,8vw,7.5rem)] leading-[1.08] tracking-[-0.035em] max-[640px]:text-[clamp(3.2rem,18vw,5.2rem)]">
            من تجويد الحروف
            <span className="block text-[0.73em] text-athar-accent">إلى معرفة الوقوف.</span>
          </h1>
          <p className="mt-[26px] max-w-[580px] text-[clamp(1rem,1.6vw,1.2rem)] text-athar-ink-soft">
            مصحف قريب من المطبوع، ووقف موثّق من المصاحف والقرّاء والعلماء — ثم
            تدريب يقيس ما تعلّمت.
          </p>
          <div className="mt-[30px] flex flex-wrap gap-2.5">
            <Link className={actionLinkClassName("primary")} href="/read?surah=2&ayah=255">
              افتح آية الكرسي
            </Link>
            <Link className={actionLinkClassName("quiet")} href="/waqf-practice?surah=2&from=255&to=255">
              درّب وقفك
            </Link>
          </div>
          <dl className="mt-[42px] grid grid-cols-3 gap-3.5 border-t border-athar-line pt-[18px] max-[640px]:grid-cols-1">
            <div className="grid gap-0.5">
              <dt className="text-[0.72rem] text-athar-ink-faint">واجهة</dt>
              <dd className="m-0 text-[0.82rem] font-bold text-athar-ink-soft">Vercel CDN</dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="text-[0.72rem] text-athar-ink-faint">البيانات</dt>
              <dd className="m-0 text-[0.82rem] font-bold text-athar-ink-soft">Python على Heroku</dd>
            </div>
            <div className="grid gap-0.5">
              <dt className="text-[0.72rem] text-athar-ink-faint">النتيجة</dt>
              <dd className="m-0 text-[0.82rem] font-bold text-athar-ink-soft">هيكل فوري، بيانات موثّقة</dd>
            </div>
          </dl>
        </div>
        <div className="[perspective:1200px] max-[920px]:mx-auto max-[920px]:w-full max-[920px]:max-w-[680px]">
          <AyahPreview />
        </div>
      </section>

      <section className={cn(pageContainerClassName, "py-[90px_120px]")} aria-labelledby="doors-title">
        <header className="mb-[38px] max-w-[720px]">
          <p className="mb-3 text-[0.78rem] font-bold tracking-[0.08em] text-athar-gold">أربعة أبواب، أثر واحد</p>
          <h2 id="doors-title" className="m-0 font-athar-display text-[clamp(2.4rem,5vw,4.6rem)] leading-[1.08] tracking-[-0.035em]">من الدليل إلى القراءة اليومية.</h2>
          <p className="text-athar-ink-soft">المصحف، وتثبيت، ومُكْث، وتدريب — أربعة أبواب على الواجهة الجديدة، والبيانات تبقى على Flask.</p>
        </header>
        <div className="grid grid-cols-4 gap-px overflow-hidden border border-athar-line bg-athar-line max-[920px]:grid-cols-2 max-[640px]:grid-cols-1">
          {doors.map((door) => {
            const content = (
              <>
                <span className="text-xs font-bold text-athar-gold">{door.verb}</span>
                <h3 className="mt-4 mb-2 font-athar-display text-4xl">{door.title}</h3>
                <p className="m-0 text-sm text-athar-ink-soft">{door.description}</p>
                <span className="mt-auto flex items-center justify-between gap-3 text-sm font-bold text-athar-accent">
                  افتح
                  <span aria-hidden="true">←</span>
                </span>
              </>
            );
            const className = "flex min-h-[310px] flex-col bg-athar-canvas p-7 no-underline transition-[background-color,transform] hover:-translate-y-1 hover:bg-athar-surface focus-visible:z-10 focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-athar-accent max-[640px]:min-h-[250px]";
            return (
              <Link className={className} href={door.href} key={door.title}>
                {content}
              </Link>
            );
          })}
        </div>
      </section>

      <section className="bg-athar-ink py-[90px] text-athar-canvas">
        <div className={cn(pageContainerClassName, "max-w-[880px]")}>
          <p className="mb-3 text-[0.78rem] font-bold tracking-[0.08em] text-athar-gold">البيانات في موضعها</p>
          <h2 className="m-0 font-athar-display text-[clamp(2.4rem,5vw,4.6rem)] leading-[1.08] tracking-[-0.035em]">الواجهة هنا، والمصحف والوقف حيث وُثّقا.</h2>
          <p className="max-w-[660px] [color:color-mix(in_srgb,var(--athar-parchment)_68%,transparent)]">
            لا نعيد كتابة منطق القرآن. الواجهة الجديدة تستعمل واجهات Flask الحالية،
            وتترك المحرّر والبحث الثقيل والخطوط المتخصصة في مكانها حتى يحين دورها.
          </p>
        </div>
      </section>

      <footer className={cn(pageContainerClassName, "flex flex-wrap items-center justify-between gap-3 border-t border-athar-line py-8 text-sm text-athar-ink-faint")}>
        <span>© أثَر — مع القرآن</span>
        <Link className="text-athar-ink-soft no-underline hover:text-athar-accent" href="/credits">المصادر والشكر</Link>
      </footer>
    </main>
  );
}
