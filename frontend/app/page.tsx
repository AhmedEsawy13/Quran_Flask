import Link from "next/link";
import {ContinueReading} from "@/components/continue-reading";
import {StopExplorer} from "@/components/stop-explorer";
import {VerseJump} from "@/components/verse-jump";
import {DoorIcon} from "@/components/ui/door-icon";
import {WaqfGlyph} from "@/components/ui/waqf-glyph";
import {cn} from "@/lib/cn";
import {supportTools, toolHref, waqfTools, type ToolKey} from "@/lib/nav";
import {pageContainerClassName} from "@/lib/ui";
import {waqfMarkGuide} from "@/lib/waqf";

const example = {surah: 2, ayah: 255};

const toolExamples: Record<ToolKey, {href: string; label: string}> = {
  waqf: {href: toolHref("waqf", example), label: "آية الكرسي"},
  lab: {href: "/waqf-lab?tab=word&family=words&q=%D8%A7%D9%84%D8%B9%D9%84%D9%8A%D9%85", label: "كل وقفٍ على «العليم»"},
  practice: {href: toolHref("practice", example), label: "درّب وقفك في آية الكرسي"},
  read: {href: toolHref("read", example), label: "افتح آية الكرسي"},
  memorize: {href: "/memorize?surah=2&from=255&to=257", label: "البقرة ٢٥٥–٢٥٧"},
};

const witnesses = [
  {
    title: "علامة المصحف",
    body: "علامات الوقف كما طُبعت في المصاحف المعتمدة — المدينة القديم والجديد، والأزهر، والشمرلي، وقطر، والكويت، والبحرين، وورش — متقابلةً على الكلمة نفسها.",
  },
  {
    title: "وقف القارئ",
    body: "مواضع الوقف مستخرجة من توقيتات تلاوات القرّاء المتقنين كالحصري والمنشاوي وعبد الباسط: من وقف، ومن وصل، ومن انفرد.",
  },
  {
    title: "حكم الإمام",
    body: "نصوص كتب الوقف والابتداء مربوطة بالكلمة المقصودة، مع درجة الوقف (تام، كاف، حسن…) وعلّته، ونسبة القول إلى قائله.",
  },
];

const books = [
  {title: "المكتفى في الوقف والابتدا", author: "أبو عمرو الداني"},
  {title: "منار الهدى في بيان الوقف والابتدا", author: "الأشموني"},
  {title: "القطع والائتناف", author: "أبو جعفر النحاس"},
  {title: "إيضاح الوقف والابتداء", author: "ابن الأنباري"},
];

const markTone = {
  strong: "text-athar-positive",
  avoid: "text-athar-negative",
  neutral: "text-athar-accent",
};

function Kicker({children, tone = "gold"}: {children: React.ReactNode; tone?: "gold" | "accent"}) {
  return (
    <p className={cn(
      "m-0 mb-3 inline-flex items-center gap-2 text-[0.78rem] font-bold tracking-[0.04em]",
      tone === "gold" ? "text-athar-gold" : "text-athar-accent",
    )}>
      <span aria-hidden="true" className={cn("h-px w-6", tone === "gold" ? "bg-athar-gold" : "bg-athar-accent")} />
      {children}
    </p>
  );
}

export default function HomePage() {
  return (
    <main id="athar-main" tabIndex={-1}>
      {/* Hero: the promise and a live proof of it. */}
      <section className={cn(
        pageContainerClassName,
        "grid grid-cols-[minmax(0,1fr)_minmax(420px,1.05fr)] items-center gap-[clamp(36px,6vw,80px)] py-[clamp(40px,7vw,88px)] max-[980px]:grid-cols-1",
      )}>
        <div>
          <p className="m-0 mb-5 inline-flex items-center gap-2 rounded-full border border-athar-accent/25 bg-athar-accent/8 px-3 py-1 text-[0.78rem] font-bold text-athar-accent">
            <DoorIcon name="waqf" className="size-4" />
            علم الوقف والابتداء
          </p>
          <h1 className="m-0 font-athar-display text-[clamp(2.9rem,6.4vw,5.6rem)] leading-[1.06] tracking-[-0.03em]">
            اعرف أين تقف،
            <span className="block text-athar-accent">ولماذا تقف.</span>
          </h1>
          <p className="mt-6 mb-0 max-w-[560px] text-[clamp(1rem,1.5vw,1.15rem)] leading-[1.85] text-athar-ink-soft">
            لكل موضع وقف في القرآن ثلاث شهادات يجمعها أثَر في مكان واحد: علامة
            المصاحف المطبوعة، ووقف القرّاء المتقنين، وحكم أئمة الوقف والابتداء —
            ثم يدرّبك حتى يصير وقفك فهمًا لا تخمينًا.
          </p>
          <VerseJump />
          <dl className="mt-9 grid max-w-[560px] grid-cols-3 gap-3 border-t border-athar-line pt-5">
            {[
              ["٨", "مصاحف مطبوعة"],
              ["١٥", "قارئًا متقنًا"],
              ["٤", "كتب في الوقف"],
            ].map(([value, label]) => (
              <div key={label} className="grid gap-0.5">
                <dt className="order-2 text-[0.78rem] font-semibold text-athar-ink-faint">{label}</dt>
                <dd className="order-1 m-0 font-athar-display text-[2rem] leading-none text-athar-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
        <StopExplorer />
      </section>

      {/* The learning path: the three waqf tools, in order. */}
      <section className="border-y border-athar-line-soft bg-athar-surface/60 py-[clamp(56px,8vw,100px)]" aria-labelledby="path-title">
        <div className={pageContainerClassName}>
          <header className="mb-10 grid max-w-[760px]">
            <Kicker>رحلة الوقف في ثلاث خطوات</Kicker>
            <h2 id="path-title" className="m-0 font-athar-display text-[clamp(2.1rem,4.4vw,3.8rem)] leading-[1.1] tracking-[-0.03em]">
              تأمّل الموضع، ثم ابحث عن نظائره، ثم اختبر نفسك.
            </h2>
          </header>
          <ol className="m-0 grid list-none grid-cols-3 gap-4 p-0 max-[900px]:grid-cols-1">
            {waqfTools.map((tool, index) => (
              <li key={tool.key} className="relative">
                <Link
                  className="group flex h-full flex-col rounded-athar-lg border border-athar-line bg-athar-surface p-6 no-underline shadow-[0_1px_0_var(--athar-line-soft)] transition-[border-color,box-shadow,transform] hover:-translate-y-1 hover:border-athar-accent/50 hover:shadow-athar-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent"
                  href={toolHref(tool.key, example)}
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="grid size-12 place-items-center rounded-2xl bg-athar-accent/10 text-athar-accent transition-colors group-hover:bg-athar-accent group-hover:text-athar-on-accent">
                      <DoorIcon name={tool.key} className="size-6" />
                    </span>
                    <span className="font-athar-display text-[2.6rem] leading-none text-athar-line">{["١", "٢", "٣"][index]}</span>
                  </span>
                  <span className="mt-6 text-[0.78rem] font-bold text-athar-gold">{tool.verb} · {tool.label}</span>
                  <h3 className="mt-1 mb-2 font-athar-display text-[1.9rem] leading-tight text-athar-ink">{tool.title}</h3>
                  <p className="m-0 text-sm leading-7 text-athar-ink-soft">{tool.description}</p>
                  <span className="mt-auto flex items-center gap-2 border-t border-athar-line-soft pt-4 text-sm font-bold text-athar-accent">
                    <span className="text-athar-ink-faint">مثال:</span>
                    {toolExamples[tool.key].label}
                    <span aria-hidden="true" className="ms-auto transition-transform group-hover:-translate-x-1">←</span>
                  </span>
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Why trust it: the three witnesses and the books behind the third. */}
      <section className="bg-athar-ink py-[clamp(56px,9vw,104px)] text-athar-canvas" aria-labelledby="witnesses-title">
        <div className={pageContainerClassName}>
          <Kicker>ثلاث شهادات على كل وقف</Kicker>
          <h2 id="witnesses-title" className="m-0 max-w-[820px] font-athar-display text-[clamp(2.1rem,4.4vw,3.9rem)] leading-[1.1] tracking-[-0.03em]">
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
          <div className="mt-10 border-t border-[color-mix(in_srgb,var(--athar-parchment)_14%,transparent)] pt-8">
            <h3 className="m-0 mb-4 text-sm font-bold text-athar-gold">كتب الوقف والابتداء في أثَر</h3>
            <ul className="m-0 grid list-none grid-cols-4 gap-3 p-0 max-[980px]:grid-cols-2 max-[520px]:grid-cols-1">
              {books.map((book) => (
                <li key={book.title} className="grid gap-1 border-s-2 border-athar-gold/60 ps-3">
                  <span className="font-athar-display text-[1.15rem] leading-snug">{book.title}</span>
                  <span className="text-[0.8rem] [color:color-mix(in_srgb,var(--athar-parchment)_62%,transparent)]">{book.author}</span>
                </li>
              ))}
            </ul>
            <Link
              className="mt-8 inline-flex items-center gap-2 border-b border-athar-gold/40 pb-0.5 text-sm font-bold text-athar-gold no-underline hover:border-athar-gold"
              href="/credits"
            >
              المصادر والرخص كاملة
              <span aria-hidden="true">←</span>
            </Link>
          </div>
        </div>
      </section>

      {/* A quick reference: the marks the reader meets on every page. */}
      <section className={cn(pageContainerClassName, "py-[clamp(56px,8vw,96px)]")} aria-labelledby="marks-title">
        <div className="grid grid-cols-[minmax(0,.8fr)_minmax(0,1.2fr)] items-start gap-10 max-[900px]:grid-cols-1">
          <header>
            <Kicker tone="accent">مرجع سريع</Kicker>
            <h2 id="marks-title" className="m-0 font-athar-display text-[clamp(2rem,3.8vw,3.2rem)] leading-[1.12] tracking-[-0.03em]">
              علامات الوقف في مصحف حفص.
            </h2>
            <p className="mt-4 mb-0 max-w-[46ch] leading-8 text-athar-ink-soft">
              العلامة وحدها لا تكفي؛ فالمصاحف تختلف في وضعها. لذلك يعرض أثَر
              علامة كل مصحف بجوار وقف القرّاء وحكم الأئمة.
            </p>
          </header>
          <ul className="m-0 grid list-none grid-cols-2 gap-2.5 p-0 max-[520px]:grid-cols-1">
            {waqfMarkGuide.map((mark) => (
              <li key={mark.symbol} className="flex items-center gap-3.5 rounded-athar-md border border-athar-line bg-athar-surface p-3.5">
                <span className={cn("grid size-12 shrink-0 place-items-center rounded-xl bg-athar-canvas", markTone[mark.tone])}>
                  <WaqfGlyph symbol={mark.symbol} className="size-10" title={mark.label} />
                </span>
                <span className="grid min-w-0">
                  <strong className="text-athar-ink">{mark.label}</strong>
                  <span className="text-[0.82rem] text-athar-ink-soft">{mark.guidance}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* Supporting tools: reading and memorisation. */}
      <section className="border-t border-athar-line-soft bg-athar-canvas-strong/50 py-[clamp(48px,7vw,84px)]" aria-labelledby="support-title">
        <div className={pageContainerClassName}>
          <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
            <header>
              <Kicker>ومعها</Kicker>
              <h2 id="support-title" className="m-0 font-athar-display text-[clamp(1.8rem,3.2vw,2.6rem)] leading-tight tracking-[-0.02em]">
                مصحف للقراءة، ومساحة للحفظ.
              </h2>
            </header>
            <ContinueReading />
          </div>
          <div className="grid grid-cols-2 gap-4 max-[760px]:grid-cols-1">
            {supportTools.map((tool) => (
              <Link
                key={tool.key}
                className="group flex items-start gap-4 rounded-athar-lg border border-athar-line bg-athar-surface p-5 no-underline transition-[border-color,transform] hover:-translate-y-0.5 hover:border-athar-accent/50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent"
                href={toolExamples[tool.key].href}
              >
                <span className="grid size-12 shrink-0 place-items-center rounded-2xl bg-athar-line-soft text-athar-ink-soft transition-colors group-hover:bg-athar-accent group-hover:text-athar-on-accent">
                  <DoorIcon name={tool.key} className="size-6" />
                </span>
                <span className="grid gap-1">
                  <span className="font-athar-display text-[1.5rem] leading-tight text-athar-ink">{tool.title}</span>
                  <span className="text-sm leading-7 text-athar-ink-soft">{tool.description}</span>
                  <span className="mt-1 text-sm font-bold text-athar-accent">{toolExamples[tool.key].label} ←</span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      <footer className={cn(pageContainerClassName, "flex flex-wrap items-center justify-between gap-4 border-t border-athar-line py-8 text-sm text-athar-ink-faint")}>
        <span>© أثَر — الوقف والابتداء</span>
      </footer>
    </main>
  );
}
