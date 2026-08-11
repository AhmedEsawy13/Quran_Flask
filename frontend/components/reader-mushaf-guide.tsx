"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { getJson, type WaqfPayload } from "@/lib/api";
import { MUSHAF_EDITIONS, toArabicDigits, type MushafEditionId } from "@/lib/mushaf";
import { useBoundedAudio } from "@/lib/use-bounded-audio";
import { commonWaqfMarks, waqfMarkDescription, waqfMarkGlyph, waqfMarkTone } from "@/lib/waqf";
import { Button, StatusState, Surface } from "@/components/ui/primitives";

type GuideResult = {
  key: string;
  data: WaqfPayload | null;
  error: string;
};

function isNativeAudio(url: string | null) {
  return Boolean(url && !/youtu(?:\.be|be\.com)/i.test(url));
}

export function ReaderMushafGuide({
  surahNumber,
  ayahNumber,
  editionId,
  reciterId,
}: {
  surahNumber: number;
  ayahNumber: number;
  editionId: MushafEditionId;
  reciterId: string;
}) {
  const edition = MUSHAF_EDITIONS[editionId];
  const [expanded, setExpanded] = useState(false);
  const [result, setResult] = useState<GuideResult>({key: "", data: null, error: ""});
  const {audioRef, playingKey, progress, play, stop} = useBoundedAudio();
  const requestKey = `${surahNumber}:${ayahNumber}`;
  const visible = result.key === requestKey ? result : null;
  const data = visible?.data || null;

  useEffect(() => {
    if (!expanded || result.key === requestKey) return;
    const controller = new AbortController();
    stop();
    getJson<WaqfPayload>(`/backend-api/waqf/${surahNumber}/${ayahNumber}`, controller.signal)
      .then((payload) => setResult({key: requestKey, data: payload, error: ""}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setResult({
          key: requestKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل دليل التلاوة.",
        });
      });
    return () => controller.abort();
  }, [expanded, requestKey, result.key, surahNumber, ayahNumber, stop]);

  useEffect(() => stop(), [surahNumber, ayahNumber, reciterId, stop]);

  const selectedReciter = useMemo(() => {
    if (!data) return null;
    const requested = data.per_reciter[reciterId];
    if (requested) return {id: reciterId, detail: requested};
    const fallback = data.reciters.find((item) => data.per_reciter[item.id]);
    return fallback ? {id: fallback.id, detail: data.per_reciter[fallback.id]} : null;
  }, [data, reciterId]);

  const marksByPosition = useMemo(() => {
    const marks = new Map<number, string>();
    if (!data) return marks;
    const preferred = data.mushafs.find((mushaf) =>
      mushaf.id === edition.waqfSource || mushaf.name === edition.waqfSource
    );
    (preferred?.marks || data.mushafs.flatMap((mushaf) => mushaf.marks)).forEach((mark) => {
      if (!marks.has(mark.wpos)) marks.set(mark.wpos, mark.symbol);
    });
    return marks;
  }, [data, edition.waqfSource]);

  return (
    <Surface
      as="aside"
      className="mx-auto w-full max-w-[790px] rounded-athar-md p-4 sm:p-5"
      aria-labelledby="mushaf-key-title"
    >
      <audio ref={audioRef} preload="metadata" className="hidden" />
      <header className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div>
          <span className="text-[0.68rem] font-bold text-athar-gold">مفتاح الصفحة</span>
          <h2 id="mushaf-key-title" className="mb-1 mt-0 font-athar-display text-2xl text-athar-ink sm:text-[1.75rem]">
            افهم ما تراه قبل أن تقرأ
          </h2>
          <p className="m-0 max-w-[560px] text-xs leading-6 text-athar-ink-soft">
            الرسم يغيّر شكل الصفحة والخط، وعلامات الوقف ترشد موضع الوقوف؛ أمّا دليل التلاوة فيعرض كيف قسّم القارئ الآية فعلًا.
          </p>
        </div>
        <a
          className="shrink-0 text-xs font-bold text-athar-accent underline-offset-4 hover:underline"
          href={`/waqf?surah=${surahNumber}&ayah=${ayahNumber}`}
        >
          قارن الأدلة في مُكْث ←
        </a>
      </header>

      <div className="grid gap-3 md:grid-cols-[minmax(0,.9fr)_minmax(0,1.4fr)]">
        <section className="rounded-xl border border-athar-line-soft bg-athar-line-soft p-3.5" aria-label="شرح الرسم المختار">
          <span className="text-[0.65rem] font-bold text-athar-gold">رسم الصفحة المختار</span>
          <strong className="mt-1 block text-sm text-athar-ink">{edition.label}</strong>
          <p className="mb-0 mt-1 text-[0.72rem] leading-5 text-athar-ink-soft">{edition.description}</p>
        </section>

        <section className="rounded-xl border border-athar-line-soft p-3.5" aria-label="شرح علامات الوقف">
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <div>
              <span className="text-[0.65rem] font-bold text-athar-gold">الحروف الصغيرة بعد الكلمات</span>
              <strong className="mt-0.5 block text-sm text-athar-ink">علامات الوقف</strong>
            </div>
            <span className="text-[0.65rem] text-athar-ink-faint">المصدر: {edition.waqfSource}</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4" aria-label="أهم رموز الوقف">
            {commonWaqfMarks.map((symbol) => {
              const description = waqfMarkDescription(symbol);
              return (
                <span className="flex min-w-0 items-center gap-2 rounded-lg bg-athar-line-soft px-2.5 py-2" key={symbol}>
                  <b className={`text-lg text-athar-ink waqf-legend-symbol is-${waqfMarkTone(symbol)}`}>{waqfMarkGlyph(symbol)}</b>
                  <span className="truncate text-[0.66rem] text-athar-ink-soft">{description.guidance}</span>
                </span>
              );
            })}
          </div>
        </section>
      </div>

      <div className="mt-3 flex flex-col items-start justify-between gap-3 rounded-xl border border-athar-accent/20 bg-athar-accent/5 px-3.5 py-3 sm:flex-row sm:items-center">
        <div>
          <strong className="block text-sm text-athar-ink">دليل التلاوة لهذه الآية</strong>
          <span className="text-[0.72rem] leading-5 text-athar-ink-soft">مقاطع قصيرة بحسب وقوف القارئ المختار، مع إمكانية سماع كل مقطع وحده.</span>
        </div>
        <Button
          size="sm"
          variant={expanded ? "quiet" : "primary"}
          aria-expanded={expanded}
          aria-controls="reader-recitation-guide"
          onClick={() => {
            if (expanded) stop();
            setExpanded((value) => !value);
          }}
        >
          {expanded ? "أخفِ الدليل" : "افتح دليل التلاوة"}
        </Button>
      </div>

      {expanded ? (
        <section id="reader-recitation-guide" className="mt-4 border-t border-athar-line-soft pt-4" aria-label="دليل التلاوة">
          {!visible ? <StatusState tone="loading" className="justify-center">جارٍ تقسيم الآية إلى مقاطع…</StatusState> : null}
          {visible?.error ? <StatusState tone="error" className="justify-center">{visible.error}</StatusState> : null}
          {data && selectedReciter ? (
            <>
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <div>
                  <span className="text-[0.65rem] font-bold text-athar-gold">اقرأ مقطعًا ثم انتقل إلى التالي</span>
                  <h3 className="mb-0 mt-0.5 font-athar-display text-xl text-athar-ink">بصوت {selectedReciter.detail.name_ar}</h3>
                </div>
                <span className="text-[0.68rem] text-athar-ink-faint">{toArabicDigits(selectedReciter.detail.phrases.length)} مقاطع</span>
              </div>
              <div className="waqf-segment-list" aria-label="مقاطع دليل التلاوة">
                {selectedReciter.detail.phrases.map((phrase, index) => {
                  const key = `reader-guide:${selectedReciter.id}:${index}`;
                  const active = playingKey === key;
                  const symbol = marksByPosition.get(phrase.last_wpos);
                  const endWord = data.words[phrase.last_wpos];
                  const isLast = index === selectedReciter.detail.phrases.length - 1;
                  const playable = isNativeAudio(selectedReciter.detail.audio_url);
                  return (
                    <button
                      type="button"
                      className={active ? "is-playing" : ""}
                      key={key}
                      disabled={!playable}
                      aria-label={`${active ? "إيقاف" : "استمع إلى"} المقطع ${toArabicDigits(index + 1)}`}
                      onClick={() => {
                        if (!selectedReciter.detail.audio_url) return;
                        void play({
                          key,
                          source: selectedReciter.detail.audio_url,
                          start: selectedReciter.detail.verse_start + phrase.start,
                          end: selectedReciter.detail.verse_start + phrase.end,
                        });
                      }}
                    >
                      <span className="waqf-segment-number">{toArabicDigits(index + 1)}</span>
                      <span className="waqf-segment-words">
                        {data.words.slice(phrase.first_wpos, phrase.last_wpos + 1).join(" ")}
                        <small className="mt-1 block font-athar-ui text-[0.65rem] text-athar-ink-faint">
                          {isLast ? "نهاية الآية" : symbol ? `${waqfMarkGlyph(symbol)} · ${waqfMarkDescription(symbol).guidance}` : `قف بعد «${endWord}»`}
                        </small>
                      </span>
                      <span className="waqf-segment-time">{active ? "Ⅱ" : "▶"} {toArabicDigits((phrase.end - phrase.start).toFixed(1))}ث</span>
                      {active ? <span className="waqf-segment-progress" style={{"--segment-progress": `${Math.round(progress * 100)}%`} as CSSProperties} /> : null}
                    </button>
                  );
                })}
              </div>
            </>
          ) : null}
        </section>
      ) : null}
    </Surface>
  );
}
