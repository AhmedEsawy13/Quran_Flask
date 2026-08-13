import type {Metadata} from "next";
import Link from "next/link";
import {cn} from "@/lib/cn";
import {pageContainerClassName} from "@/lib/ui";

export const metadata: Metadata = {
  title: "المصادر والشكر",
  description: "مصادر النص والتجويد والتفسير وكتب الوقف والخطوط التي يعتمد عليها أثَر — مع نسبها ورخصها.",
  alternates: {canonical: "/credits"},
};

export default function CreditsPage() {
  return (
    <>
    <main id="athar-main" className={pageContainerClassName} tabIndex={-1}>
      <header className="mx-auto max-w-[720px] py-[clamp(36px,6vw,72px)]">
        <p className="mb-3 font-athar-display text-2xl text-athar-accent">أثَر</p>
        <h1 className="m-0 font-athar-display text-[clamp(2.4rem,5vw,4.2rem)] leading-[1.08]">المصادر والشكر</h1>
        <p className="mt-4 max-w-[58ch] text-[1.05rem] leading-8 text-athar-ink-soft">
          أثَر يعتمد على مصادر علمية وخطوط مفتوحة — هنا نسبها باختصار، حتى يبقى التلوين والبيان والتفسير والوقف على بيّنة.
        </p>
      </header>

      <div className="mx-auto mb-16 grid max-w-[720px] gap-10">
        <section aria-labelledby="cr-tajweed">
          <h2 id="cr-tajweed" className="m-0 font-athar-display text-3xl">التجويد</h2>
          <ul className="mt-4 grid list-none gap-5 p-0">
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">تلوين الأحكام</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">
                بيانات الألوان مبنيّة على مشروع{" "}
                <a href="https://github.com/cpfair/quran-tajweed" target="_blank" rel="noopener">cpfair/quran-tajweed</a>
                {" "}(رخصة CC-BY 4.0)، مع نص عثماني من Tanzil — وتُعرض محليًا عبر <code>/api/tajweed</code>.
              </p>
            </li>
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">بيان التجويد</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">
                الشروح النصّية بجانب التلوين من{" "}
                <a href="https://tafsir.net" target="_blank" rel="noopener">مركز تفسير للدراسات القرآنية</a>
                {" "}عبر{" "}
                <a href="https://github.com/tafsircenter/tafsir-mcp" target="_blank" rel="noopener">Tafsir MCP</a>
                {" "}— مخزّنة محليًا وليست بديلاً عن الألوان.
              </p>
            </li>
          </ul>
        </section>

        <section aria-labelledby="cr-tafsir">
          <h2 id="cr-tafsir" className="m-0 font-athar-display text-3xl">التفسير</h2>
          <p className="mt-3 mb-0 leading-8 text-athar-ink-soft">
            خمسة تفاسير عربية على صفحة المصحف، مبنية من صادرات{" "}
            <a href="https://qul.tarteel.ai" target="_blank" rel="noopener">QUL (qul.tarteel.ai)</a>
            {" "}وتُخدم من بيانات محلية:
          </p>
          <ul className="mt-3 columns-1 gap-x-8 p-0 ps-5 text-athar-ink-soft sm:columns-2">
            <li>التفسير الميسر — مجمع الملك فهد</li>
            <li>المختصر في التفسير</li>
            <li>تيسير الكريم الرحمن (السعدي)</li>
            <li>الجامع لأحكام القرآن (القرطبي)</li>
            <li>معالم التنزيل (البغوي)</li>
          </ul>
        </section>

        <section aria-labelledby="cr-waqf">
          <h2 id="cr-waqf" className="m-0 font-athar-display text-3xl">الوقف والابتداء</h2>
          <ul className="mt-4 grid list-none gap-5 p-0">
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">علامات المصاحف</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">علامات الوقف في الطبعات المعتمدة داخل التطبيق (المدينة وغيرها) كما ضُبطت في بيانات التخطيط المحلية.</p>
            </li>
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">كتب الوقف الكلاسيكية</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">
                المكتفى (الداني)، منار الهدى (الأشموني)، القطع والائتناف (النحاس)، وإيضاح الوقف (ابن الأنباري) — من طبعات{" "}
                <a href="https://openiti.org/" target="_blank" rel="noopener">OpenITI</a>
                ، مع محاذاة إلى مواضع الكلمات في أثَر.
              </p>
            </li>
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">وقوف القرّاء</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">
                مواضع الوقف المستخرجة من توقيتات التلاوة — للمقارنة في مُكْث، لا كحكم شرعي مستقل.
                من القرّاء المعتمدين في التطبيق مثل: محمود خليل الحصري، محمد صديق المنشاوي، عبد الباسط عبد الصمد، إبراهيم الأخضر، أيمن سويد، وغيرهم.
              </p>
            </li>
          </ul>
        </section>

        <section aria-labelledby="cr-asbab">
          <h2 id="cr-asbab" className="m-0 font-athar-display text-3xl">أسباب النزول</h2>
          <p className="mt-3 mb-0 leading-8 text-athar-ink-soft">
            إن ثبتت في المصادر المحمّلة من{" "}
            <a href="https://tafsir.net" target="_blank" rel="noopener">مركز تفسير</a>
            {" "}(الواحدي ولباب النقول / تحقيق الحميدان) عبر Tafsir MCP — تغطية جزئية، وغياب البيان لا ينفي النزول.
          </p>
        </section>

        <section aria-labelledby="cr-text">
          <h2 id="cr-text" className="m-0 font-athar-display text-3xl">النص والخطوط</h2>
          <ul className="mt-4 grid list-none gap-5 p-0">
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">رسم المصحف</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">تخطيطات المدينة (Digital Khatt / QPC) وغيرها من مصادر الرسم المعتمدة في المشروع للعرض والمحاكاة.</p>
            </li>
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">خطوط الواجهة</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">
                عائلة{" "}
                <a href="https://font.thmanyah.com/" target="_blank" rel="noopener">Thmanyah</a>
                {" "}لواجهة أثَر والعناوين — وخطوط المصحف العثمانية تبقى لعرض الآيات.
              </p>
            </li>
            <li>
              <h3 className="m-0 text-base font-bold text-athar-ink">الصوت</h3>
              <p className="mt-1.5 mb-0 leading-8 text-athar-ink-soft">ملفات التلاوة وتوقيت الكلمات من مصادر القرّاء المستخدمة في المصحف وتثبيت ومُكْث؛ تُخدم محليًا أو عبر المسارات المضبوطة في النشر.</p>
            </li>
          </ul>
        </section>

        <section aria-labelledby="cr-note">
          <h2 id="cr-note" className="m-0 font-athar-display text-3xl">تنبيه</h2>
          <p className="mt-3 mb-0 leading-8 text-athar-ink-soft">
            أثَر أداة مساعدة للدراسة والتدريب. المحاكاة الرقمية للرسم قريبة من المطبوع وليست مطابقة حرفًا بحرف.
            راجع عالمًا مختصًا للأحكام التفصيلية.
          </p>
        </section>
      </div>
    </main>

    <footer className={cn(pageContainerClassName, "flex max-w-[720px] flex-wrap items-center justify-between gap-3 border-t border-athar-line py-8 text-sm text-athar-ink-faint")}>
      <span>© أثَر — مع القرآن</span>
      <nav className="flex flex-wrap gap-4" aria-label="روابط">
        <Link className="text-athar-ink-soft no-underline hover:text-athar-accent" href="/">الرئيسية</Link>
        <Link className="text-athar-ink-soft no-underline hover:text-athar-accent" href="/read">المصحف</Link>
        <Link className="text-athar-ink-soft no-underline hover:text-athar-accent" href="/waqf">مُكْث</Link>
        <Link className="text-athar-ink-soft no-underline hover:text-athar-accent" href="/waqf-practice">تدريب</Link>
      </nav>
    </footer>
  </>
  );
}
