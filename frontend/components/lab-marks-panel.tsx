"use client";

import {useEffect, useState} from "react";
import {getJson, type Surah} from "@/lib/api";
import {cn} from "@/lib/cn";
import {toArabicDigits} from "@/lib/mushaf";
import {HIT_PAGE, type MarkSearchPayload, type MarkSummary} from "@/lib/waqf-lab";
import {HitList, HitRow} from "@/components/waqf-lab-hit";
import {WaqfGlyph} from "@/components/ui/waqf-glyph";
import {StatusState} from "@/components/ui/primitives";

/** A Hafs glyph that stands for each meaning in the picker. */
const MEANING_GLYPH: Record<string, string> = {
  MUST: "م", STOP: "ق", CONT: "ص", CHOICE: "ج", NOSTOP: "لا", EMBRACE: "ع", SAKTA: "س", ABS: "ؕ",
};

const chip = "inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 text-[0.82rem] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40";

/** «Every وقف لازم in the Azhar mushaf»: pick a mushaf, then what its mark tells the reader. */
export function LabMarksPanel({surahs}: {surahs: Surah[]}) {
  const [summary, setSummary] = useState<MarkSummary | null>(null);
  const [mushaf, setMushaf] = useState("المدينة الجديد");
  const [mark, setMark] = useState("MUST");
  const [result, setResult] = useState<{key: string; data: MarkSearchPayload | null; error: string}>({key: "", data: null, error: ""});
  const [shown, setShown] = useState(HIT_PAGE);
  const key = `${mushaf}|${mark}`;

  useEffect(() => {
    getJson<MarkSummary>("/backend-api/waqf-research/marks/summary").then(setSummary).catch(() => setSummary({meanings: [], mushafs: []}));
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getJson<MarkSearchPayload>(`/backend-api/waqf-research/marks?mushaf=${encodeURIComponent(mushaf)}&mark=${mark}`, controller.signal)
      .then((data) => setResult({key, data, error: ""}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setResult({key, data: null, error: "تعذّر تحميل المواضع."});
      });
    return () => controller.abort();
  }, [key, mushaf, mark]);

  const counts = summary?.mushafs.find((item) => item.id === mushaf)?.counts || {};
  const visible = result.key === key ? result : null;

  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <span className="text-[0.74rem] font-bold text-athar-ink-faint">١. المصحف</span>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="المصحف">
          {(summary?.mushafs || []).map((item) => (
            <button
              type="button"
              role="radio"
              aria-checked={mushaf === item.id}
              key={item.id}
              onClick={() => {
                setMushaf(item.id);
                setShown(HIT_PAGE);
                if (!item.counts[mark]) setMark(summary?.meanings.find((meaning) => item.counts[meaning.id])?.id || mark);
              }}
              className={cn(chip, mushaf === item.id ? "border-athar-accent bg-athar-accent text-athar-on-accent" : "border-athar-line bg-athar-surface text-athar-ink-soft hover:border-athar-accent")}
            >
              {item.id}
            </button>
          ))}
        </div>
      </div>
      <div className="grid gap-2">
        <span className="text-[0.74rem] font-bold text-athar-ink-faint">٢. معنى العلامة</span>
        <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="معنى العلامة">
          {(summary?.meanings || []).map((meaning) => {
            const count = counts[meaning.id] || 0;
            return (
              <button
                type="button"
                role="radio"
                aria-checked={mark === meaning.id}
                key={meaning.id}
                disabled={!count}
                title={count ? undefined : `لا يستعمل ${mushaf} هذه العلامة`}
                onClick={() => {
                  setMark(meaning.id);
                  setShown(HIT_PAGE);
                }}
                className={cn(chip, mark === meaning.id ? "border-athar-accent bg-athar-accent/10 text-athar-accent" : "border-athar-line bg-athar-surface text-athar-ink-soft hover:border-athar-accent")}
              >
                <WaqfGlyph symbol={MEANING_GLYPH[meaning.id] || ""} className="size-[1.4em]" />
                {meaning.label}
                <b className="tabular-nums">{toArabicDigits(count)}</b>
              </button>
            );
          })}
        </div>
      </div>
      {!visible ? <StatusState tone="loading">جارٍ جمع المواضع…</StatusState> : null}
      {visible?.error ? <StatusState tone="error">{visible.error}</StatusState> : null}
      {visible?.data ? (
        <HitList
          items={visible.data.occurrences}
          shown={shown}
          onShowMore={() => setShown((value) => value + HIT_PAGE)}
          empty={`لا يضع ${mushaf} علامة «${visible.data.label}» في أي موضع.`}
          renderItem={(item, index) => (
            <HitRow
              occurrence={item}
              surahName={surahs.find((surah) => surah.number === item.surah)?.name}
              key={`${item.surah}:${item.ayah}:${item.wpos}:${index}`}
            />
          )}
        />
      ) : null}
    </div>
  );
}
