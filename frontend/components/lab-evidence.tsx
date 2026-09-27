"use client";

import Link from "next/link";
import {useEffect, useState} from "react";
import {getJson, type ClassicalWaqfPayload, type WaqfPayload} from "@/lib/api";
import {arabicCount, toArabicDigits} from "@/lib/mushaf";
import {ImamRulings} from "@/components/imam-rulings";
import {StatusState} from "@/components/ui/primitives";

/** Where the stop being studied sits. `wpos: -1` = the ayah's last word. */
export type EvidenceTarget = {surah: number; ayah: number; wpos: number};

type AyahEnd = {reciters_total: number; joined: string[]};
type VerseEvidence = {waqf: WaqfPayload | null; classical: ClassicalWaqfPayload | null; ayahEnd: AyahEnd | null};

const verseCache = new Map<string, Promise<VerseEvidence>>();

function loadVerse(surah: number, ayah: number) {
  const key = `${surah}:${ayah}`;
  let job = verseCache.get(key);
  if (!job) {
    job = Promise.all([
      getJson<WaqfPayload>(`/backend-api/waqf/${surah}/${ayah}`).catch(() => null),
      getJson<ClassicalWaqfPayload>(`/backend-api/classical-waqf/${surah}/${ayah}`).catch(() => null),
      // Ayah ends are absent from the within-ayah stops; ask who joined this one to the next.
      getJson<AyahEnd>(`/backend-api/waqf-research/ayah-end/${surah}/${ayah}`).catch(() => null),
    ]).then(([waqf, classical, ayahEnd]) => ({waqf, classical, ayahEnd}));
    verseCache.set(key, job);
  }
  return job;
}

/**
 * The three witnesses for one stop, shown in place under a lab result:
 * how many reciters stopped there, and what the imams ruled.
 */
export function LabEvidence({target}: {target: EvidenceTarget}) {
  const [evidence, setEvidence] = useState<VerseEvidence | null>(null);

  useEffect(() => {
    let live = true;
    void loadVerse(target.surah, target.ayah).then((result) => {
      if (live) setEvidence(result);
    });
    return () => {
      live = false;
    };
  }, [target.surah, target.ayah]);

  if (!evidence) return <StatusState tone="loading" className="min-h-10">جارٍ جمع الأدلة…</StatusState>;
  const {waqf, classical, ayahEnd} = evidence;
  const wpos = target.wpos < 0 ? Math.max(0, (waqf?.words.length || 1) - 1) : target.wpos;
  const atAyahEnd = Boolean(waqf && wpos === waqf.words.length - 1);
  const union = waqf?.union_stops.find((stop) => stop.wpos === wpos);
  const stopped = union?.count ?? 0;
  const total = waqf?.reciters_total ?? 0;
  const rulings = (classical?.entries || []).filter((entry) => entry.wpos === wpos);
  const word = waqf?.words[wpos];

  return (
    <div className="grid gap-3 rounded-xl border border-athar-line-soft bg-athar-canvas/70 p-3" aria-label="أدلة الموضع">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[0.8rem] text-athar-ink-soft">
          الوقف بعد {word ? <b className="font-athar-quran text-[1.05rem] text-athar-ink">{word}</b> : "هذا الموضع"}
        </span>
        <Link
          className="text-[0.78rem] font-bold text-athar-accent no-underline hover:underline"
          href={`/waqf?surah=${target.surah}&ayah=${target.ayah}&wpos=${wpos}`}
        >
          التفصيل الكامل في مُكْث ←
        </Link>
      </div>
      <div className="grid gap-1.5">
        <span className="text-[0.72rem] font-bold text-athar-gold">القرّاء</span>
        {atAyahEnd && ayahEnd ? (
          <span className="text-[0.8rem] text-athar-ink">
            {ayahEnd.joined.length
              ? `رأس آية — وصله بما بعده ${ayahEnd.joined.length === 1 ? ayahEnd.joined[0] : `${toArabicDigits(ayahEnd.joined.length)} من ${arabicCount(ayahEnd.reciters_total, ["قارئ واحد", "قارئين", "قرّاء", "قارئًا"])}`}، ووقف الباقون`
              : `رأس آية — وقف عليه القرّاء جميعًا (${toArabicDigits(ayahEnd.reciters_total)})`}
          </span>
        ) : total ? (
          <div className="flex items-center gap-2.5">
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-athar-line-soft">
              <span className="block h-full rounded-full bg-athar-accent" style={{width: `${(stopped / total) * 100}%`}} />
            </span>
            <span className="shrink-0 text-[0.8rem] text-athar-ink">
              {stopped
                ? union?.solo
                  ? `انفرد بالوقف ${waqf?.per_reciter[union.reciters[0]]?.name_ar || "قارئ"}`
                  : `وقف ${toArabicDigits(stopped)} من ${arabicCount(total, ["قارئ واحد", "قارئين", "قرّاء", "قارئًا"])}`
                : `وصل القرّاء جميعًا (${toArabicDigits(total)})`}
            </span>
          </div>
        ) : (
          <span className="text-[0.8rem] text-athar-ink-faint">لا توجد تلاوات محلّلة لهذه الآية بعد.</span>
        )}
      </div>
      <div className="grid gap-1.5">
        <span className="text-[0.72rem] font-bold text-athar-gold">الأئمة</span>
        {rulings.length && classical ? (
          <ImamRulings entries={rulings} sources={classical.sources} showQuote={false} />
        ) : (
          <span className="text-[0.8rem] text-athar-ink-faint">لا نصّ لهذا الموضع في كتب الوقف المتاحة.</span>
        )}
      </div>
    </div>
  );
}
