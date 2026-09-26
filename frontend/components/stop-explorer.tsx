"use client";

import Link from "next/link";
import {useEffect, useMemo, useState} from "react";
import {getJson, type ClassicalWaqfPayload, type WaqfPayload} from "@/lib/api";
import {cn} from "@/lib/cn";
import {toArabicDigits} from "@/lib/mushaf";
import {waqfMarkCanonical, waqfMarkLabel} from "@/lib/waqf";

const SURAH = 2;
const AYAH = 255;

type Stop = {
  wpos: number;
  mushafs: Array<{name: string; symbol: string}>;
  reciters: number;
  rulings: Array<{imam: string; book: string; grade: string}>;
};

type Loaded = {waqf: WaqfPayload; classical: ClassicalWaqfPayload | null};

const gradeTone: Record<string, string> = {
  "تام": "bg-athar-accent text-athar-on-accent",
  "كاف": "bg-athar-positive/15 text-athar-positive",
  "حسن": "bg-athar-gold/15 text-athar-gold",
};

function buildStops({waqf, classical}: Loaded): Stop[] {
  const lastWord = waqf.words.length - 1;
  const stops = new Map<number, Stop>();
  const at = (wpos: number) => {
    let stop = stops.get(wpos);
    if (!stop) {
      stop = {wpos, mushafs: [], reciters: 0, rulings: []};
      stops.set(wpos, stop);
    }
    return stop;
  };
  waqf.mushafs.forEach((mushaf) => mushaf.marks.forEach((mark) => {
    at(mark.wpos).mushafs.push({name: mushaf.name, symbol: waqfMarkCanonical(mark.symbol)});
  }));
  waqf.union_stops.forEach((stop) => {
    at(stop.wpos).reciters = stop.count;
  });
  classical?.entries.forEach((entry) => {
    const source = classical.sources[entry.source];
    const stop = at(entry.wpos);
    const imam = source?.name || entry.source;
    if (!stop.rulings.some((ruling) => ruling.imam === imam && ruling.grade === entry.grade)) {
      stop.rulings.push({imam, book: source?.title || "", grade: entry.grade});
    }
  });
  // The ayah end is always a stop; the interesting decisions are inside it.
  stops.delete(lastWord);
  return [...stops.values()].sort((a, b) => a.wpos - b.wpos);
}

/** Open on the most instructive stop: the imams rule on it, yet the mushafs disagree most. */
function mostContested(stops: Stop[]) {
  const ruled = stops.filter((stop) => stop.rulings.length);
  const pool = ruled.length ? ruled : stops;
  return pool.reduce<Stop | null>((best, stop) => (!best || stop.mushafs.length < best.mushafs.length ? stop : best), null);
}

function commonestMark(stop: Stop) {
  const counts = new Map<string, number>();
  stop.mushafs.forEach(({symbol}) => counts.set(symbol, (counts.get(symbol) || 0) + 1));
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] || null;
}

function Meter({value, max, label}: {value: number; max: number; label: string}) {
  return (
    <span className="block h-1.5 overflow-hidden rounded-full bg-athar-line-soft" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <span className="block h-full rounded-full bg-athar-accent transition-[width] duration-500" style={{width: `${max ? (value / max) * 100 : 0}%`}} />
    </span>
  );
}

function Witness({index, title, children}: {index: string; title: string; children: React.ReactNode}) {
  return (
    <div className="grid content-start gap-2 rounded-2xl border border-athar-line-soft bg-athar-canvas/70 p-3.5 @max-[34rem]:grid-cols-[7.5rem_minmax(0,1fr)] @max-[34rem]:items-center @max-[34rem]:py-2.5">
      <span className="flex items-center gap-2 text-[0.72rem] font-bold text-athar-gold">
        <span className="grid size-5 shrink-0 place-items-center rounded-full bg-athar-gold/12 font-athar-display">{index}</span>
        {title}
      </span>
      <div className="grid min-w-0 gap-1.5">{children}</div>
    </div>
  );
}

export function StopExplorer() {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<WaqfPayload>(`/backend-api/waqf/${SURAH}/${AYAH}`, controller.signal),
      getJson<ClassicalWaqfPayload>(`/backend-api/classical-waqf/${SURAH}/${AYAH}`, controller.signal).catch(() => null),
    ])
      .then(([waqf, classical]) => setLoaded({waqf, classical}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(true);
      });
    return () => controller.abort();
  }, []);

  const stops = useMemo(() => (loaded ? buildStops(loaded) : []), [loaded]);
  const stopByWpos = useMemo(() => new Map(stops.map((stop) => [stop.wpos, stop])), [stops]);
  const current = (selected !== null ? stopByWpos.get(selected) : null) || mostContested(stops);
  const mushafTotal = loaded?.waqf.mushafs.length || 0;
  const reciterTotal = loaded?.waqf.reciters_total || 0;
  const mark = current ? commonestMark(current) : null;

  return (
    <article
      className="@container relative overflow-hidden rounded-[22px] border border-athar-line bg-athar-surface shadow-athar-lg"
      aria-labelledby="explorer-title"
    >
      <span aria-hidden="true" className="pointer-events-none absolute -top-24 -start-24 size-64 rounded-full bg-athar-accent/10 blur-3xl" />
      <header className="relative flex flex-wrap items-center justify-between gap-2 border-b border-athar-line-soft px-5 py-3.5">
        <div className="grid leading-tight">
          <span className="text-[0.7rem] font-bold text-athar-gold">جرّب الآن</span>
          <h2 id="explorer-title" className="m-0 font-athar-display text-xl text-athar-ink">آية الكرسي · البقرة {toArabicDigits(AYAH)}</h2>
        </div>
        {stops.length ? (
          <span className="rounded-full bg-athar-accent/10 px-2.5 py-1 text-[0.72rem] font-bold text-athar-accent">
            {toArabicDigits(stops.length)} مواضع وقف · اضغط أيّها
          </span>
        ) : null}
      </header>

      <div className="relative px-5 pt-5 pb-3">
        {loaded ? (
          <p className="m-0 font-athar-quran text-[clamp(1.35rem,2.3vw,1.8rem)] leading-[2.25] text-athar-ink" dir="rtl">
            {loaded.waqf.words.map((word, wpos) => {
              const stop = stopByWpos.get(wpos);
              if (!stop) return <span key={wpos}>{word} </span>;
              const active = current?.wpos === wpos;
              return (
                <span key={wpos}>
                  <button
                    type="button"
                    onClick={() => setSelected(wpos)}
                    aria-pressed={active}
                    aria-label={`موضع الوقف عند «${word}»`}
                    className={cn(
                      "cursor-pointer rounded-lg px-1 font-[inherit] underline decoration-dotted decoration-2 underline-offset-[0.55em] transition-colors",
                      active
                        ? "bg-athar-accent text-athar-on-accent decoration-transparent"
                        : "text-athar-accent decoration-athar-accent/45 hover:bg-athar-accent/10",
                    )}
                  >
                    {word}
                  </button>{" "}
                </span>
              );
            })}
          </p>
        ) : error ? (
          <div className="grid gap-2 py-10 text-center text-athar-ink-soft">
            <strong className="text-athar-ink">تعذّر تحميل المثال الآن</strong>
            <Link className="font-bold text-athar-accent" href={`/waqf?surah=${SURAH}&ayah=${AYAH}`}>افتح الآية في مُكْث ←</Link>
          </div>
        ) : (
          <div className="verse-skeleton py-6" aria-label="جارٍ تحميل آية الكرسي">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>

      {current && loaded ? (
        <div className="relative grid gap-3 px-5 pb-5" aria-live="polite">
          <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-sm text-athar-ink-soft">
            الوقف عند
            <b className="font-athar-quran text-lg text-athar-ink">{loaded.waqf.words[current.wpos]}</b>
            {current.mushafs.length === mushafTotal ? (
              <span className="rounded-full bg-athar-positive/12 px-2 py-0.5 text-[0.7rem] font-bold text-athar-positive">المصاحف متفقة</span>
            ) : (
              <span className="rounded-full bg-athar-copper/12 px-2 py-0.5 text-[0.7rem] font-bold text-athar-copper">موضع خلاف</span>
            )}
          </p>
          <div className="grid gap-2 @min-[34rem]:grid-cols-3 @min-[34rem]:gap-2.5">
            <Witness index="١" title="علامة المصاحف">
              <strong className="font-athar-display text-2xl leading-none text-athar-ink">
                {toArabicDigits(current.mushafs.length)}<small className="text-sm text-athar-ink-faint"> من {toArabicDigits(mushafTotal)}</small>
              </strong>
              <Meter value={current.mushafs.length} max={mushafTotal} label="المصاحف التي تضع علامة" />
              <span className="text-[0.74rem] leading-5 text-athar-ink-soft">
                {mark ? <>أغلبها «{mark}» — {waqfMarkLabel(mark)}</> : "لا علامة في المصاحف"}
              </span>
            </Witness>
            <Witness index="٢" title="وقف القرّاء">
              <strong className="font-athar-display text-2xl leading-none text-athar-ink">
                {toArabicDigits(current.reciters)}<small className="text-sm text-athar-ink-faint"> من {toArabicDigits(reciterTotal)}</small>
              </strong>
              <Meter value={current.reciters} max={reciterTotal} label="القرّاء الذين وقفوا هنا" />
              <span className="text-[0.74rem] leading-5 text-athar-ink-soft">
                {current.reciters ? "قارئًا وقفوا هنا في تلاواتهم" : "لم يقف هنا أحد من القرّاء"}
              </span>
            </Witness>
            <Witness index="٣" title="حكم الأئمة">
              {current.rulings.length ? (
                <ul className="m-0 grid list-none gap-1.5 p-0">
                  {current.rulings.map((ruling) => (
                    <li key={`${ruling.imam}:${ruling.grade}`} className="flex items-center justify-between gap-2 text-[0.8rem] text-athar-ink">
                      <span className="truncate" title={ruling.book}>{ruling.imam}</span>
                      <span className={cn("rounded-full px-2 py-0.5 text-[0.7rem] font-bold", gradeTone[ruling.grade] || "bg-athar-line-soft text-athar-ink-soft")}>
                        {ruling.grade}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <span className="text-[0.74rem] leading-5 text-athar-ink-soft">لا نصّ لهذا الموضع في الكتب المتاحة</span>
              )}
            </Witness>
          </div>
          <Link
            className="group inline-flex w-fit items-center gap-2 text-sm font-bold text-athar-accent no-underline"
            href={`/waqf?surah=${SURAH}&ayah=${AYAH}&wpos=${current.wpos}`}
          >
            افتح هذا الموضع بأدلته كاملة في مُكْث
            <span aria-hidden="true" className="transition-transform group-hover:-translate-x-1">←</span>
          </Link>
        </div>
      ) : null}
    </article>
  );
}
