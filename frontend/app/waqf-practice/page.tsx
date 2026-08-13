import type {Metadata} from "next";
import {Suspense} from "react";
import {PracticeWorkspace} from "@/components/practice-workspace";
import {ToolIntro} from "@/components/tool-chrome";
import {RouteSkeleton} from "@/components/ui/primitives";
import {introLinkClassName} from "@/lib/ui";
import {legacyUrl} from "@/lib/paths";

export const metadata: Metadata = {
  title: "تدريب",
  description: "علّم أين وقفت، ثم قيّم وقوفك على علامات المصاحف المطبوعة.",
  alternates: {canonical: "/waqf-practice"},
};

export default function PracticePage() {
  return (
    <div id="athar-main" tabIndex={-1}>
      <ToolIntro
        kicker="— تدريب"
        title="علِّم وقوفــك، وقيّمه بالمطبوع."
        titleId="wp-title"
        titleAriaLabel="علّم وقفك، وقيّمه بالمطبوع."
        lede="اختر مقطعًا ومصحفًا، ثم علّم أين وقفت. أثَر يقيّمك على علامات المصاحف — لا بالتخمين."
      >
        <ol className="m-0 flex list-none flex-wrap gap-x-[18px] gap-y-2 p-0" aria-label="خطوات التدريب">
          <li className="inline-flex items-center gap-2 text-[0.86rem] font-semibold text-athar-ink-soft">
            <b className="grid size-[1.55rem] place-items-center rounded-full bg-athar-accent/12 font-athar-display text-[0.78rem] font-extrabold text-athar-accent">١</b>
            <span>اختر المقطع</span>
          </li>
          <li className="inline-flex items-center gap-2 text-[0.86rem] font-semibold text-athar-ink-soft">
            <b className="grid size-[1.55rem] place-items-center rounded-full bg-athar-accent/12 font-athar-display text-[0.78rem] font-extrabold text-athar-accent">٢</b>
            <span>علّم وقوفك</span>
          </li>
          <li className="inline-flex items-center gap-2 text-[0.86rem] font-semibold text-athar-ink-soft">
            <b className="grid size-[1.55rem] place-items-center rounded-full bg-athar-accent/12 font-athar-display text-[0.78rem] font-extrabold text-athar-accent">٣</b>
            <span>راجع التقييم</span>
          </li>
        </ol>
        <a className={introLinkClassName()} href={legacyUrl("/waqf-practice")}>التسجيل الصوتي</a>
      </ToolIntro>
      <Suspense fallback={<RouteSkeleton label="جارٍ تجهيز جلسة التدريب" />}>
        <PracticeWorkspace />
      </Suspense>
    </div>
  );
}
