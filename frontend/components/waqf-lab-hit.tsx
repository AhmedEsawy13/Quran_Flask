import type {ReactNode} from "react";
import Link from "next/link";
import {toArabicDigits} from "@/lib/mushaf";
import {cn} from "@/lib/cn";
import {Button, StatusState} from "@/components/ui/primitives";
import {
  editorEditionsFromMarks,
  editorHref,
  mushafFontClass,
  mushafGlyph,
  verseHref,
  type ResearchOccurrence,
  type WaqfMarks,
} from "@/lib/waqf-lab";

export function AgreePill({agreement}: {agreement?: string}) {
  if (agreement === "full") return <ToneChip tone="consensus">تام</ToneChip>;
  if (agreement === "partial") return <ToneChip tone="solo">جزئي</ToneChip>;
  return null;
}

export function ToneChip({
  tone = "muted",
  children,
  className,
}: {
  tone?: "consensus" | "solo" | "accent" | "muted";
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[0.7rem] font-bold",
        tone === "consensus" && "bg-athar-waqf-consensus/16 text-athar-waqf-consensus",
        tone === "solo" && "bg-athar-waqf-solo-soft text-athar-waqf-solo",
        tone === "accent" && "bg-athar-accent/10 text-athar-accent",
        tone === "muted" && "bg-athar-line-soft font-semibold text-athar-ink-soft",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function LabWide({children, className}: {children: ReactNode; className?: string}) {
  return <div className={cn("hidden lg:block", className)}>{children}</div>;
}

export function LabNarrow({children, className}: {children: ReactNode; className?: string}) {
  return <div className={cn("grid lg:hidden", className)}>{children}</div>;
}

export function LabTable({children}: {children: ReactNode}) {
  return (
    <LabWide className="overflow-x-auto">
      <table className="w-full border-collapse text-[0.82rem] [&_td]:border-b [&_td]:border-athar-line-soft [&_td]:px-1.5 [&_td]:py-1.5 [&_td]:text-center [&_th]:sticky [&_th]:top-0 [&_th]:border-b [&_th]:border-athar-line-soft [&_th]:bg-athar-surface [&_th]:px-1.5 [&_th]:py-1.5 [&_th]:text-center">
        {children}
      </table>
    </LabWide>
  );
}

export function HitMarks({marks}: {marks?: WaqfMarks}) {
  const entries = Object.entries(marks || {});
  if (!entries.length) return <span className="text-[0.78rem] text-athar-ink-faint">بلا علامة مطبوعة</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {entries.map(([mushaf, symbol]) => (
        <span
          className="inline-flex items-center gap-1 rounded-full border border-athar-line-soft bg-athar-surface px-2 py-0.5 text-[0.72rem] text-athar-ink-soft"
          key={`${mushaf}-${symbol}`}
          title={mushaf}
        >
          <span className={cn(mushafFontClass(mushaf), "text-[1.05rem] text-athar-accent")}>{mushafGlyph(symbol, mushaf)}</span>
          <span>{mushaf}</span>
        </span>
      ))}
    </div>
  );
}

export function HitRow({
  occurrence,
  surahName,
  hideMarks,
  marks,
  meta,
  flow,
  title,
  extraClass,
  editorEditions,
}: {
  occurrence: Pick<ResearchOccurrence, "surah" | "ayah" | "wpos" | "word" | "context" | "marks">;
  surahName?: string;
  hideMarks?: boolean;
  marks?: ReactNode;
  meta?: ReactNode;
  flow?: ReactNode;
  title?: string;
  extraClass?: string;
  editorEditions?: string[];
}) {
  const name = surahName || `سورة ${toArabicDigits(occurrence.surah)}`;
  const ref = `${toArabicDigits(occurrence.surah)}:${toArabicDigits(occurrence.ayah)}`;
  const editions = editorEditions || editorEditionsFromMarks(occurrence.marks);
  return (
    <div className="grid gap-1.5">
      <Link
        className={cn(
          "grid gap-1.5 rounded-xl border border-athar-line bg-athar-surface px-3 py-2.5 no-underline transition-colors hover:border-athar-accent hover:bg-athar-accent/6",
          extraClass,
        )}
        href={verseHref(occurrence.surah, occurrence.ayah, {wpos: occurrence.wpos, word: occurrence.word})}
        title={title || `افتح ${name} ${ref}`}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <span className="text-[0.78rem] font-bold text-athar-ink-soft">
            {name} <b className="text-athar-accent">{ref}</b>
          </span>
          {meta ? <span className="inline-flex flex-wrap items-center gap-1">{meta}</span> : null}
        </div>
        {flow ? <div className="flex flex-wrap items-center gap-1.5 text-sm">{flow}</div> : null}
        {occurrence.context ? (
          <div className="font-athar-quran text-[1.05rem] leading-8 text-athar-ink" dir="rtl">{occurrence.context}</div>
        ) : null}
        {marks ? marks : hideMarks ? null : <HitMarks marks={occurrence.marks} />}
      </Link>
      {editions.length ? (
        <div className="flex flex-wrap gap-2 ps-1">
          {editions.map((edition) => (
            <a
              className="text-[0.72rem] font-bold text-athar-accent no-underline hover:underline"
              href={editorHref(edition, occurrence.surah, occurrence.ayah)}
              key={edition}
            >
              محرّر · {edition}
            </a>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function HitChip({children, muted}: {children: ReactNode; muted?: boolean}) {
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5",
        muted
          ? "border-dashed border-athar-line text-[0.78rem] text-athar-ink-soft"
          : "border-athar-line bg-athar-canvas font-athar-quran text-[0.95rem] text-athar-ink",
      )}
    >
      {children}
    </span>
  );
}

export function HitList<T>({
  items,
  shown,
  onShowMore,
  renderItem,
  empty = "لا نتائج",
}: {
  items: T[];
  shown: number;
  onShowMore: () => void;
  renderItem: (item: T, index: number) => ReactNode;
  empty?: string;
}) {
  if (!items.length) return <StatusState>{empty}</StatusState>;
  const visible = items.slice(0, shown);
  return (
    <div className="grid gap-2">
      {visible.map((item, index) => renderItem(item, index))}
      {shown < items.length ? (
        <Button variant="secondary" className="justify-self-start" onClick={onShowMore}>
          عرض المزيد · بقي {toArabicDigits(items.length - shown)}
        </Button>
      ) : null}
    </div>
  );
}

export function ToolBlurb({shortText, longText}: {shortText: string; longText?: string}) {
  if (!longText) return <p className="m-0 text-[0.86rem] leading-6 text-athar-ink-soft">{shortText}</p>;
  return (
    <details className="text-[0.86rem] leading-6 text-athar-ink-soft">
      <summary className="cursor-pointer font-semibold text-athar-ink">{shortText}</summary>
      <p className="mt-1.5 mb-0">{longText}</p>
    </details>
  );
}

export function CountLabel({children}: {children: ReactNode}) {
  return <p className="m-0 text-[0.82rem] font-bold text-athar-accent">{children}</p>;
}
