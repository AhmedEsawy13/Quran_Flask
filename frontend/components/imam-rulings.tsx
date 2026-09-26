"use client";

import {useState, type ReactNode} from "react";
import type {ClassicalWaqfPayload} from "@/lib/api";
import {cn} from "@/lib/cn";
import {classicalGradeMeta, isNegativeGrade} from "@/lib/waqf";

type Entry = ClassicalWaqfPayload["entries"][number];
type Sources = ClassicalWaqfPayload["sources"];

const LONG_NOTE = 240;

const gradeStyle: Record<string, string> = {
  tamm: "bg-athar-positive text-athar-on-accent",
  kafi: "bg-athar-accent/12 text-athar-accent",
  hasan: "bg-athar-gold/15 text-athar-gold",
  jaiz: "bg-athar-line-soft text-athar-ink-soft",
  qabih: "bg-athar-negative/12 text-athar-negative",
};

/** What each grade tells a reader, in plain words. */
const gradeMeaning: Record<string, string> = {
  "تام": "قف، وابدأ بما بعده — انقطع اللفظ والمعنى.",
  "لازم": "قف ولا بدّ — الوصل يوهم معنًى غير مراد.",
  "كاف": "قف، وابدأ بما بعده — ما بعده متصل بالمعنى فقط.",
  "صالح": "يصلح الوقف والابتداء بما بعده.",
  "حسن": "يحسن الوقف، ولا يحسن الابتداء بما بعده — عُد إلى ما قبله.",
  "جائز": "يجوز الوقف والوصل.",
  "لا": "لا تقف هنا — ما بعده متعلّق بما قبله.",
  "قبيح": "لا تقف هنا — الوقف يُخلّ بالمعنى.",
};

/** Quran words quoted in the علّة — «…» or {…} — set in the Quran face. */
function withQuranQuotes(text: string): ReactNode[] {
  return text.split(/(«[^»]+»|\{[^}]+\})/g).filter(Boolean).map((part, index) => (
    /^[«{]/.test(part)
      ? <span key={index} className="font-athar-quran text-[1.22em] leading-none text-athar-accent">{part.replace(/^\{|\}$/g, "")}</span>
      : part
  ));
}

function Illa({note}: {note: string}) {
  const [open, setOpen] = useState(false);
  const long = note.length > LONG_NOTE;
  return (
    <div className="grid gap-1">
      <p className={cn("m-0 text-[0.94rem] leading-[1.95] text-athar-ink", long && !open && "line-clamp-4")}>
        <span className="me-1.5 text-[0.72rem] font-bold text-athar-ink-faint">العلّة:</span>
        {withQuranQuotes(note)}
      </p>
      {long ? (
        <button
          type="button"
          className="w-fit cursor-pointer border-0 bg-transparent p-0 text-[0.8rem] font-bold text-athar-accent hover:underline"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {open ? "اطوِ العلّة" : "اقرأ العلّة كاملة"}
        </button>
      ) : null}
    </div>
  );
}

/** «قاله: أبو حاتم» reads right whatever case the book wrote the name in; «قيل» names no one. */
function attribution(reportedFrom: string) {
  const name = reportedFrom.trim();
  return name === "قيل" ? "قولٌ منقول بلا تسمية (وقيل)" : `قاله: ${name}`;
}

function verdict(entries: Entry[], sources: Sources) {
  const grades = [...new Set(entries.map((entry) => entry.grade))];
  const imams = [...new Set(entries.map((entry) => entry.source))];
  if (imams.length < 2) return null;
  if (grades.length === 1) {
    return {agree: true, text: `اتفق ${imams.map((id) => sources[id]?.name || id).join(" و")}: ${grades[0]}`};
  }
  const negative = grades.some(isNegativeGrade);
  const positive = grades.some((grade) => !isNegativeGrade(grade));
  return {agree: false, text: negative && positive ? "اختلف الأئمة: منهم من أجاز الوقف ومنهم من منعه" : "اختلف الأئمة في درجة الوقف"};
}

/**
 * The classical imams' rulings on one stop: grouped per imam, each grade with
 * its plain meaning, and the علّة readable at body size.
 */
export function ImamRulings({entries, sources, showQuote = true}: {entries: Entry[]; sources: Sources; showQuote?: boolean}) {
  const unique = entries.filter((entry, index, list) => (
    list.findIndex((item) => item.source === entry.source && item.grade === entry.grade && item.note === entry.note) === index
  ));
  const byImam = new Map<string, Entry[]>();
  unique.forEach((entry) => byImam.set(entry.source, [...(byImam.get(entry.source) || []), entry]));
  const summary = verdict(unique, sources);

  return (
    <div className="grid gap-2.5">
      {summary ? (
        <p className={cn(
          "m-0 w-fit rounded-full px-3 py-1 text-[0.78rem] font-bold",
          summary.agree ? "bg-athar-positive/12 text-athar-positive" : "bg-athar-copper/12 text-athar-copper",
        )}>
          {summary.text}
        </p>
      ) : null}
      {[...byImam].map(([sourceId, rulings]) => {
        const source = sources[sourceId];
        return (
          <article key={sourceId} className="grid gap-3 rounded-xl border border-athar-line-soft bg-athar-surface p-3.5">
            <header className="grid gap-0.5">
              <strong className="text-[0.95rem] text-athar-ink">{source?.name || sourceId}</strong>
              {source?.title ? <span className="text-[0.74rem] text-athar-ink-faint">{source.title}</span> : null}
            </header>
            {rulings.map((entry, index) => {
              const meta = classicalGradeMeta[entry.grade];
              const note = (entry.note || "").trim();
              const quote = (entry.quote || "").trim();
              return (
                <div key={`${entry.grade}-${index}`} className={cn("grid gap-2", index > 0 && "border-t border-dashed border-athar-line pt-3")}>
                  {index > 0 ? <span className="text-[0.72rem] font-bold text-athar-ink-faint">وجهٌ آخر عنده</span> : null}
                  <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                    <span className={cn("rounded-lg px-2.5 py-1 text-[0.95rem] font-extrabold leading-none", gradeStyle[meta?.cls || "jaiz"])} title={meta?.desc}>
                      {entry.grade_raw || entry.grade}
                    </span>
                    <span className="text-[0.8rem] text-athar-ink-soft">{gradeMeaning[entry.grade] || meta?.desc}</span>
                  </div>
                  {entry.reported_from ? (
                    <span className="w-fit rounded-full bg-athar-gold/10 px-2 py-0.5 text-[0.72rem] font-bold text-athar-gold">
                      {attribution(entry.reported_from)}
                    </span>
                  ) : null}
                  {showQuote && quote.split(/\s+/).length > 4 ? (
                    <blockquote className="m-0 border-s-2 border-athar-gold/50 ps-3 font-athar-quran text-[1.05rem] leading-[1.9] text-athar-ink">
                      {quote}
                    </blockquote>
                  ) : null}
                  {note ? <Illa note={note} /> : null}
                </div>
              );
            })}
          </article>
        );
      })}
    </div>
  );
}
