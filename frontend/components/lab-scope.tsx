"use client";

import {createContext, useContext, useMemo, type ReactNode} from "react";
import type {Surah} from "@/lib/api";
import {cn} from "@/lib/cn";
import {arabicCount, juzLabel, juzNumberFromAyah, toArabicDigits} from "@/lib/mushaf";

/** A lab tool's reach: the whole Quran, one surah, or one juz. */
export type LabScope = {surah: number | null; juz: number | null};

type ScopeState = {
  scope: LabScope;
  setScope: (scope: LabScope) => void;
  surahs: Surah[];
};

const LabScopeContext = createContext<ScopeState | null>(null);

export function LabScopeProvider({value, children}: {value: ScopeState; children: ReactNode}) {
  return <LabScopeContext.Provider value={value}>{children}</LabScopeContext.Provider>;
}

export function useLabScope() {
  return useContext(LabScopeContext);
}

type Located = {surah: number; ayah: number};

function located(item: unknown): item is Located {
  return Boolean(item && typeof item === "object"
    && Number.isInteger((item as Located).surah) && Number.isInteger((item as Located).ayah));
}

export function inScope(item: unknown, scope: LabScope) {
  if (!located(item)) return true;
  if (scope.surah) return item.surah === scope.surah;
  if (scope.juz) return juzNumberFromAyah(item.surah, item.ayah) === scope.juz;
  return true;
}

export function scopeLabel(scope: LabScope, surahs: Surah[]) {
  if (scope.surah) return `سورة ${surahs.find((surah) => surah.number === scope.surah)?.name || toArabicDigits(scope.surah)}`;
  if (scope.juz) return juzLabel(scope.juz);
  return "القرآن كله";
}

const selectClassName = "min-h-9 rounded-[10px] border border-athar-line bg-athar-surface px-2.5 text-[0.82rem] text-athar-ink outline-none focus:border-athar-accent";

/** Where the current tool looks: القرآن كله، سورة، or جزء. */
export function LabScopeBar() {
  const state = useLabScope();
  if (!state) return null;
  const {scope, setScope, surahs} = state;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="نطاق البحث">
      <span className="text-[0.74rem] font-bold text-athar-ink-faint">النطاق</span>
      <select
        className={selectClassName}
        aria-label="السورة"
        value={scope.surah ?? ""}
        onChange={(event) => setScope({surah: event.target.value ? Number(event.target.value) : null, juz: null})}
      >
        <option value="">كل السور</option>
        {surahs.map((surah) => (
          <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
        ))}
      </select>
      <select
        className={selectClassName}
        aria-label="الجزء"
        value={scope.juz ?? ""}
        onChange={(event) => setScope({surah: null, juz: event.target.value ? Number(event.target.value) : null})}
      >
        <option value="">كل الأجزاء</option>
        {Array.from({length: 30}, (_, index) => index + 1).map((juz) => (
          <option key={juz} value={juz}>{juzLabel(juz)}</option>
        ))}
      </select>
      {scope.surah || scope.juz ? (
        <button
          type="button"
          className="min-h-9 rounded-full px-2.5 text-[0.78rem] font-bold text-athar-accent hover:bg-athar-accent/8"
          onClick={() => setScope({surah: null, juz: null})}
        >
          القرآن كله
        </button>
      ) : null}
    </div>
  );
}

/**
 * Where a result set falls across the 114 surahs: a strip to see it at a
 * glance, and the busiest surahs as one-tap scopes.
 */
export function ScopeDistribution({items}: {items: unknown[]}) {
  const state = useLabScope();
  const counts = useMemo(() => {
    const perSurah = new Array<number>(115).fill(0);
    items.forEach((item) => {
      if (located(item) && item.surah >= 1 && item.surah <= 114) perSurah[item.surah] += 1;
    });
    return perSurah;
  }, [items]);
  if (!state) return null;
  const {scope, setScope, surahs} = state;
  const max = Math.max(...counts);
  const spread = counts.filter(Boolean).length;
  if (max === 0 || spread < 2) return null;
  const busiest = counts
    .map((count, surah) => ({surah, count}))
    .filter(({count}) => count)
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  const name = (surah: number) => surahs.find((item) => item.number === surah)?.name || toArabicDigits(surah);

  return (
    <div className="grid gap-2 rounded-xl border border-athar-line-soft bg-athar-canvas/60 p-3" aria-label="توزيع النتائج على السور">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-[0.76rem] text-athar-ink-soft">
        <span>في {arabicCount(spread, ["سورة واحدة", "سورتين", "سور", "سورة"])} — اضغط سورة لحصر النتائج فيها</span>
        <span className="text-athar-ink-faint">الفاتحة ← الناس</span>
      </div>
      <div className="grid h-7 grid-cols-[repeat(114,minmax(0,1fr))] items-end gap-px" dir="rtl">
        {counts.slice(1).map((count, index) => {
          const surah = index + 1;
          const active = scope.surah === surah;
          return (
            <button
              type="button"
              key={surah}
              disabled={!count}
              title={`${name(surah)} · ${toArabicDigits(count)}`}
              aria-label={`${name(surah)}: ${toArabicDigits(count)}`}
              onClick={() => setScope({surah: active ? null : surah, juz: null})}
              className={cn(
                "w-full rounded-[1px] transition-colors",
                count ? "cursor-pointer" : "cursor-default",
                active ? "bg-athar-copper" : count ? "bg-athar-accent hover:bg-athar-copper" : "bg-athar-line-soft",
              )}
              style={{height: count ? `${Math.max(18, (count / max) * 100)}%` : "12%", opacity: count ? 0.35 + 0.65 * (count / max) : 1}}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[0.72rem] font-bold text-athar-ink-faint">أكثر السور</span>
        {busiest.map(({surah, count}) => (
          <button
            type="button"
            key={surah}
            onClick={() => setScope({surah: scope.surah === surah ? null : surah, juz: null})}
            aria-pressed={scope.surah === surah}
            className={cn(
              "min-h-7 rounded-full border px-2.5 text-[0.76rem] font-semibold transition-colors",
              scope.surah === surah ? "border-athar-copper bg-athar-copper text-athar-on-accent" : "border-athar-line bg-athar-surface text-athar-ink-soft hover:border-athar-accent",
            )}
          >
            {name(surah)} <b className="tabular-nums">{toArabicDigits(count)}</b>
          </button>
        ))}
      </div>
    </div>
  );
}
