import Link from "next/link";
import { AyahPreview } from "@/components/ayah-preview";
import { ContinueReading } from "@/components/continue-reading";
import { DoorIcon, type DoorKey } from "@/components/ui/door-icon";
import {cn} from "@/lib/cn";
import {actionLinkClassName, pageContainerClassName} from "@/lib/ui";

const doors: Array<{key: DoorKey; verb: string; title: string; description: string; href: string}> = [
  {
    key: "read",
    verb: "اقرأ",
    title: "المصحف",
    description: "رسم مصحفي هادئ، وموضعك محفوظ، وأدواتك تظهر حين تحتاجها.",
    href: "/read?surah=2&ayah=255",
  },
  {
    key: "waqf",
    verb: "تأمّل",
    title: "مُكْث",
    description: "علامة المصحف، ووقف القارئ، وقول الإمام — ثم نفسك وكل القرّاء.",
    href: "/waqf?surah=2&ayah=255",
  },
  {
    key: "memorize",
    verb: "احفظ",
    title: "تثبيت",
    description: "المصحف يملأ الشاشة. كرّر وأخفِ على الصفحة نفسها.",
    href: "/memorize?surah=2&from=255&to=257",
  },
  {
    key: "practice",
    verb: "تدرّب",
    title: "تدريب",
    description: "علّم مواضع وقوفك، ثم قارنها بالدليل بدل التخمين.",
    href: "/waqf-practice?surah=2&from=255&to=255",
  },
];

const highlights = ["رسم قريب من المطبوع", "وقف موثّق بمصادره", "تدريب يقيّم وقفك"];

const witnesses = [
  {
    title: "علامة المصحف",
    body: "علامات الوقف كما طُبعت في المصاحف المعتمدة — المدينة والأزهر والشمرلي وغيرها — تُقارن على الآية نفسها.",
  },
  {
    title: "وقف القارئ",
    body: "مواضع الوقف المستخرجة من توقيتات التلاوة لقرّاء مثل الحصري والمنشاوي وعبد الباسط — للمقارنة لا للحكم.",
  },
  {
    title: "قول الإمام",
    body: "نصوص كتب الوقف: المكتفى للداني، ومنار الهدى للأشموني، والقطع والائتناف للنحاس، وإيضاح الوقف لابن الأنباري.",
  },
];

export default function HomePage() {
  return (
    <main id="athar-main" tabIndex={-1}>
      <section className={cn(
        pageContainerClassName,
        "grid min-h-[calc(100svh-var(--bar-height))] grid-cols-[minmax(0,.9fr)_minmax(420px,1.1fr)] items-center gap-[clamp(44px,8vw,104px)] py-[70px] max-[920px]:min-h-0 max-[920px]:grid-cols-1 max-[640px]:gap-[46px] max-[640px]:py-[40px_56px]",
      )}>
        <div className="max-[920px]:max-w-[760px]">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-athar-gold/25 bg-athar-gold/8 px-3 py-1 text-[0.78rem] font-bold text-athar-gold">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-athar-gold" />
            أثَر — مع القرآن
          </p>
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
          <ContinueReading />
          <ul className="mt-9 flex list-none flex-wrap gap-x-5 gap-y-2 border-t border-athar-line p-0 pt-5" aria-label="ما يميّز أثَر">
            {highlights.map((item) => (
              <li className="inline-flex items-center gap-2 text-[0.84rem] font-semibold text-athar-ink-soft" key={item}>
                <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 fill-none stroke-athar-accent stroke-[2.2] [stroke-linecap:round] [stroke-linejoin:round]"><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
                {item}
              </li>
            ))}
          </ul>
        </div>
        <div className="[perspective:1200px] max-[920px]:mx-auto max-[920px]:w-full max-[920px]:max-w-[680px]">
          <AyahPreview />
        </div>
      </section>

      <section className={cn(pageContainerClassName, "py-[clamp(56px,9vw,110px)]")} aria-labelledby="doors-title">
        <header className="mb-[38px] max-w-[720px]">
          <p className="mb-3 text-[0.78rem] font-bold tracking-[0.08em] text-athar-gold">أربعة أبواب، أثر واحد</p>
          <h2 id="doors-title" className="m-0 font-athar-display text-[clamp(2.4rem,5vw,4.6rem)] leading-[1.08] tracking-[-0.035em]">من الدليل إلى القراءة اليومية.</h2>
          <p className="text-athar-ink-soft">اقرأ على صفحة المصحف، وتأمّل مواضع الوقف، واحفظ بالتكرار، ثم اختبر نفسك.</p>
        </header>
        <div className="grid grid-cols-4 gap-4 max-[1020px]:grid-cols-2 max-[560px]:grid-cols-1">
          {doors.map((door) => (
            <Link
              className="group flex min-h-[280px] flex-col rounded-athar-md border border-athar-line bg-athar-surface p-6 no-underline shadow-[0_1px_0_var(--athar-line-soft)] transition-[border-color,box-shadow,transform] hover:-translate-y-1 hover:border-athar-accent/50 hover:shadow-athar-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent max-[560px]:min-h-0 max-[560px]:p-5"
              href={door.href}
              key={door.title}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="grid size-12 place-items-center rounded-2xl bg-athar-accent/10 text-athar-accent transition-colors group-hover:bg-athar-accent group-hover:text-athar-on-accent">
                  <DoorIcon name={door.key} className="size-6" />
                </span>
                <span className="rounded-full bg-athar-gold/10 px-2.5 py-0.5 text-xs font-bold text-athar-gold">{door.verb}</span>
              </span>
              <h3 className="mt-6 mb-2 font-athar-display text-[2.1rem] leading-none max-[560px]:mt-4">{door.title}</h3>
              <p className="m-0 text-sm leading-7 text-athar-ink-soft">{door.description}</p>
              <span className="mt-auto flex items-center gap-2 pt-5 text-sm font-bold text-athar-accent">
                افتح {door.title}
                <span aria-hidden="true" className="transition-transform group-hover:-translate-x-1">←</span>
              </span>
            </Link>
          ))}
        </div>
      </section>

      <section className="bg-athar-ink py-[clamp(56px,9vw,96px)] text-athar-canvas" aria-labelledby="witnesses-title">
        <div className={pageContainerClassName}>
          <p className="mb-3 text-[0.78rem] font-bold tracking-[0.08em] text-athar-gold">ثلاث شهادات على كل وقف</p>
          <h2 id="witnesses-title" className="m-0 max-w-[820px] font-athar-display text-[clamp(2.2rem,4.6vw,4.2rem)] leading-[1.1] tracking-[-0.03em]">
            لا نخمّن موضع الوقف — نعرض دليله.
          </h2>
          <div className="mt-10 grid grid-cols-3 gap-4 max-[860px]:grid-cols-1">
            {witnesses.map((item, index) => (
              <article
                className="rounded-athar-md border border-[color-mix(in_srgb,var(--athar-parchment)_14%,transparent)] bg-[color-mix(in_srgb,var(--athar-parchment)_5%,transparent)] p-6"
                key={item.title}
              >
                <span className="font-athar-display text-3xl text-athar-gold">{["١", "٢", "٣"][index]}</span>
                <h3 className="mt-3 mb-2 text-lg font-bold">{item.title}</h3>
                <p className="m-0 text-sm leading-7 [color:color-mix(in_srgb,var(--athar-parchment)_72%,transparent)]">{item.body}</p>
              </article>
            ))}
          </div>
          <Link
            className="mt-8 inline-flex items-center gap-2 border-b border-athar-gold/40 pb-0.5 text-sm font-bold text-athar-gold no-underline hover:border-athar-gold"
            href="/credits"
          >
            المصادر والرخص كاملة
            <span aria-hidden="true">←</span>
          </Link>
        </div>
      </section>

      <footer className={cn(pageContainerClassName, "flex flex-wrap items-center justify-between gap-4 border-t border-athar-line py-8 text-sm text-athar-ink-faint")}>
        <span>© أثَر — مع القرآن</span>
        <Link className="text-athar-ink-soft no-underline hover:text-athar-accent" href="/credits">المصادر والشكر</Link>
      </footer>
    </main>
  );
}
