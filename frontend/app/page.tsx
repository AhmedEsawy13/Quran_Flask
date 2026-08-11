import Link from "next/link";
import { AyahPreview } from "@/components/ayah-preview";
import { legacyUrl } from "@/lib/paths";

const doors = [
  {
    verb: "اقرأ",
    title: "المصحف",
    description: "رسم مصحفي هادئ، وموضعك محفوظ، وأدواتك تظهر حين تحتاجها.",
    href: "/read?surah=2&ayah=255",
    migrated: true,
  },
  {
    verb: "تأمّل",
    title: "مُكْث",
    description: "قارن علامة المصحف، ووقف القارئ، وقول الإمام في آية واحدة.",
    href: "/waqf?surah=2&ayah=255",
    migrated: true,
  },
  {
    verb: "احفظ",
    title: "تثبيت",
    description: "تكرار مقطّع على صفحات المصحف، وبصوت القارئ الذي تختاره.",
    href: "/memorize?surah=2&from=255&to=257",
    migrated: true,
  },
  {
    verb: "تدرّب",
    title: "تدريب",
    description: "علّم مواضع وقوفك، ثم قارنها بالدليل بدل التخمين.",
    href: legacyUrl("/waqf-practice"),
    migrated: false,
  },
];

export default function HomePage() {
  return (
    <main id="athar-main" tabIndex={-1}>
      <section className="hero shell-width">
        <div className="hero-copy">
          <p className="eyebrow">أثَر — مع القرآن</p>
          <h1>
            من تجويد الحروف
            <span>إلى معرفة الوقوف.</span>
          </h1>
          <p className="hero-lede">
            مصحف قريب من المطبوع، ووقف موثّق من المصاحف والقرّاء والعلماء — ثم
            تدريب يقيس ما تعلّمت.
          </p>
          <div className="hero-actions">
            <Link className="button button-primary" href="/read?surah=2&ayah=255">
              افتح آية الكرسي
            </Link>
            <a className="button button-quiet" href={legacyUrl("/waqf-practice")}>
              درّب وقفك
            </a>
          </div>
          <dl className="hero-proof">
            <div>
              <dt>واجهة</dt>
              <dd>Vercel CDN</dd>
            </div>
            <div>
              <dt>البيانات</dt>
              <dd>Python على Heroku</dd>
            </div>
            <div>
              <dt>النتيجة</dt>
              <dd>هيكل فوري، بيانات موثّقة</dd>
            </div>
          </dl>
        </div>
        <div className="hero-visual">
          <AyahPreview />
        </div>
      </section>

      <section className="doors shell-width" aria-labelledby="doors-title">
        <header className="section-heading">
          <p className="eyebrow">أربعة أبواب، أثر واحد</p>
          <h2 id="doors-title">من الدليل إلى القراءة اليومية.</h2>
          <p>المصحف وتثبيت ومُكْث انتقلت إلى Next.js؛ بقية الأدوات تبقى آمنة على Flask أثناء النقل.</p>
        </header>
        <div className="door-grid">
          {doors.map((door) => {
            const content = (
              <>
                <span className="door-verb">{door.verb}</span>
                <h3>{door.title}</h3>
                <p>{door.description}</p>
                <span className="door-link">
                  {door.migrated ? "افتح المسار التجريبي" : "افتح النسخة الحالية"}
                  <span aria-hidden="true">←</span>
                </span>
              </>
            );
            return door.migrated ? (
              <Link className="door-card" href={door.href} key={door.title}>
                {content}
              </Link>
            ) : (
              <a className="door-card" href={door.href} key={door.title}>
                {content}
              </a>
            );
          })}
        </div>
      </section>

      <section className="migration-strip">
        <div className="shell-width migration-strip-inner">
          <p className="eyebrow">القياس قبل النقل</p>
          <h2>نثبت السرعة على المصحف، ثم ننقل ما ينجح.</h2>
          <p>
            لا نعيد كتابة منطق القرآن. الواجهة الجديدة تستعمل واجهات Flask الحالية،
            وتترك المحرّر والبحث الثقيل والخطوط المتخصصة في مكانها حتى يحين دورها.
          </p>
        </div>
      </section>
    </main>
  );
}
