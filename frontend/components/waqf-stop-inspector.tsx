"use client";

import type {ClassicalWaqfPayload, TawjihPayload, WaqfPayload} from "@/lib/api";
import {cn} from "@/lib/cn";
import {toArabicDigits} from "@/lib/mushaf";
import {classicalGradeMeta, isNegativeGrade, majorityWaqfSymbol, waqfMarkCanonical, waqfMarkLabel} from "@/lib/waqf";
import {TawjihEntryCard} from "@/components/waqf-tawjih";

function isNativeAudio(url: string | null | undefined) {
  return Boolean(url && !/youtu(?:\.be|be\.com)/i.test(url));
}

const NOTE_PREVIEW = 320;

/** The printed mark as letters (ج، ق، صلى…): the bare combining glyph has no base to sit on. */
function markLetters(symbol: string) {
  return symbol.split(/[،,]/).map((token) => waqfMarkCanonical(token)).filter(Boolean).join(" ");
}

function Row({id, title, summary, children}: {id: string; title: string; summary?: React.ReactNode; children: React.ReactNode}) {
  return (
    <section className="wq-score-row" aria-labelledby={id}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="wq-score-label" id={id}>{title}</h3>
        {summary ? <span className="text-[0.72rem] font-bold text-athar-ink-faint">{summary}</span> : null}
      </div>
      <div className="wq-score-body">{children}</div>
    </section>
  );
}

/**
 * Everything known about one stop, side by side: the printed mushafs, the
 * reciters, the classical imams, and contemporary توجيه.
 */
export function WaqfStopInspector({
  data,
  classical,
  tawjih,
  wpos,
  stopPositions,
  playingKey,
  onSelectStop,
  onPlayStop,
  onShowAllTawjih,
}: {
  data: WaqfPayload;
  classical: ClassicalWaqfPayload | null;
  tawjih: TawjihPayload | null;
  wpos: number | null;
  stopPositions: number[];
  playingKey: string | null;
  onSelectStop: (wpos: number) => void;
  onPlayStop: (reciterId: string, wpos: number) => void;
  onShowAllTawjih: () => void;
}) {
  if (wpos === null) {
    return (
      <div id="waqf-comparison" className="rounded-athar-md border border-athar-line bg-athar-surface p-5 text-[0.88rem] text-athar-ink-soft">
        لا توجد مواضع وقف مسجّلة في هذه الآية بعد.
      </div>
    );
  }

  const index = stopPositions.indexOf(wpos);
  const union = data.union_stops.find((item) => item.wpos === wpos) || null;
  const marks = data.mushafs
    .map((mushaf) => ({mushaf, mark: mushaf.marks.find((item) => item.wpos === wpos) || null}));
  const marked = marks.filter((item) => item.mark);
  const majority = majorityWaqfSymbol(marked.map((item) => item.mark!.symbol));
  const stoppedReciters = data.reciters.filter((reciter) => (
    union?.reciters.includes(reciter.id)
    || Boolean(data.per_reciter[reciter.id]?.stops.some((item) => item.wpos === wpos))
  ));
  const listenTo = stoppedReciters.find((reciter) => isNativeAudio(data.per_reciter[reciter.id]?.audio_url));
  const rulings = (classical?.entries || [])
    .filter((entry) => entry.wpos === wpos)
    .filter((entry, position, list) => list.findIndex((item) => item.source === entry.source && item.grade === entry.grade) === position);
  const tawjihHere = (tawjih?.entries || []).filter((entry) => entry.wpos === wpos);
  const tawjihElsewhere = (tawjih?.entries.length || 0) - tawjihHere.length;
  const author = tawjih?.source?.author || "د. أحمد صابر عبدالهادي";
  const isLastWord = wpos === data.words.length - 1;
  const imamsRuleOut = rulings.length > 0 && rulings.every((entry) => isNegativeGrade(entry.grade));
  const othersStop = Boolean(union || marked.length);

  return (
    <div id="waqf-comparison" className="grid scroll-mt-4 gap-3" aria-label="تفصيل موضع الوقف">
      <header className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-athar-md border border-athar-line bg-athar-surface px-4 py-3 shadow-athar-sm">
        <div className="grid min-w-0 gap-0.5">
          <span className="text-[0.72rem] font-bold text-athar-gold">
            {isLastWord ? "نهاية الآية" : imamsRuleOut && !othersStop ? "لا وقف بعد" : "الوقف بعد"}
            {index >= 0 ? <> · الموضع {toArabicDigits(index + 1)} من {toArabicDigits(stopPositions.length)}</> : null}
          </span>
          <span className="flex flex-wrap items-baseline gap-2">
            <strong className="font-athar-quran text-[1.6rem] leading-tight text-athar-ink">{data.words[wpos]}</strong>
            {union?.solo ? (
              <em className="rounded-full bg-[var(--wq-solo-soft)] px-2 py-0.5 text-[0.68rem] not-italic font-bold text-[var(--wq-solo)]">انفراد قارئ</em>
            ) : null}
            {imamsRuleOut ? (
              <em className="rounded-full bg-athar-negative/12 px-2 py-0.5 text-[0.68rem] not-italic font-bold text-athar-negative">
                {othersStop ? "الأئمة ينهون عن الوقف هنا" : "نهى الأئمة عن الوقف"}
              </em>
            ) : null}
            {data.mushafs.length && marked.length === data.mushafs.length ? (
              <em className="rounded-full bg-athar-positive/12 px-2 py-0.5 text-[0.68rem] not-italic font-bold text-athar-positive">المصاحف متفقة</em>
            ) : marked.length ? (
              <em className="rounded-full bg-athar-copper/12 px-2 py-0.5 text-[0.68rem] not-italic font-bold text-athar-copper">خلاف بين المصاحف</em>
            ) : null}
          </span>
        </div>
        {stopPositions.length > 1 && index >= 0 ? (
          <div className="flex gap-1.5">
            <button
              type="button"
              className="grid size-9 place-items-center rounded-[10px] border border-athar-line bg-athar-canvas text-lg text-athar-ink-soft transition-colors hover:border-athar-accent hover:text-athar-accent disabled:opacity-40"
              aria-label="الموضع السابق"
              aria-keyshortcuts="["
              disabled={index <= 0}
              onClick={() => onSelectStop(stopPositions[index - 1])}
            >
              ›
            </button>
            <button
              type="button"
              className="grid size-9 place-items-center rounded-[10px] border border-athar-line bg-athar-canvas text-lg text-athar-ink-soft transition-colors hover:border-athar-accent hover:text-athar-accent disabled:opacity-40"
              aria-label="الموضع التالي"
              aria-keyshortcuts="]"
              disabled={index >= stopPositions.length - 1}
              onClick={() => onSelectStop(stopPositions[index + 1])}
            >
              ‹
            </button>
          </div>
        ) : null}
      </header>

      <div className="wq-score-panel">
        <Row
          id="wq-score-mushaf"
          title="مصحف"
          summary={data.mushafs.length ? `${toArabicDigits(marked.length)} من ${toArabicDigits(data.mushafs.length)}` : undefined}
        >
          {data.mushafs.length ? (
            <div className="grid grid-cols-4 gap-1.5">
              {marks.map(({mushaf, mark}) => {
                const minority = Boolean(mark && majority && waqfMarkCanonical(mark.symbol) !== majority);
                return (
                  <div
                    className={cn(
                      "flex flex-col items-center gap-0.5 rounded-lg border px-1 py-1.5",
                      mark ? "border-athar-line-soft bg-athar-surface" : "border-transparent",
                    )}
                    key={mushaf.id}
                    title={mark ? `${mushaf.name} · ${waqfMarkLabel(mark.symbol)}` : `${mushaf.name} · لا علامة`}
                  >
                    <strong className={cn("wq-score-mushaf-glyph text-[1.3rem]", !mark && "is-empty", minority && "is-minority")}>
                      {mark ? markLetters(mark.symbol) : "—"}
                    </strong>
                    <span className="wq-score-mushaf-name max-w-full truncate">{mushaf.name}</span>
                  </div>
                );
              })}
            </div>
          ) : null}
          {majority || marked.length === 1 ? (
            <p className="wq-score-caption">
              {waqfMarkLabel(majority || marked[0].mark!.symbol)}
              {marked.some(({mark}) => majority && waqfMarkCanonical(mark!.symbol) !== majority) ? " — وبعضها يخالف (بلون مختلف)" : ""}
            </p>
          ) : null}
          {!marked.length ? <p className="wq-score-empty">لا تحمل المصاحف المقارنة علامةً هنا.</p> : null}
        </Row>

        <Row
          id="wq-score-reciters"
          title="قرّاء"
          summary={data.reciters_total ? `${toArabicDigits(stoppedReciters.length)} من ${toArabicDigits(data.reciters_total)}` : undefined}
        >
          <div className="wq-score-track flex-wrap" role="list">
            {data.reciters.map((reciter) => {
              const detail = data.per_reciter[reciter.id];
              const name = reciter.name_ar || detail?.name_ar || reciter.id;
              const stopped = stoppedReciters.includes(reciter);
              const native = isNativeAudio(detail?.audio_url);
              const key = `stop:${reciter.id}:${wpos}`;
              return (
                <button
                  type="button"
                  role="listitem"
                  className={cn(
                    "wq-score-dot",
                    stopped && "is-stop",
                    stopped && union?.solo && "is-solo",
                    playingKey === key && "is-playing",
                    !native && "is-muted",
                  )}
                  key={reciter.id}
                  title={`${name} — ${stopped ? "وقف هنا" : "وصل"}`}
                  aria-label={`${name} — ${stopped ? "وقف هنا، استمع" : "وصل"}`}
                  disabled={!(stopped && native)}
                  onClick={() => onPlayStop(reciter.id, wpos)}
                />
              );
            })}
          </div>
          {stoppedReciters.length ? (
            <p className="wq-score-caption">
              {stoppedReciters.length <= 3
                ? `وقف: ${stoppedReciters.map((reciter) => reciter.name_ar || data.per_reciter[reciter.id]?.name_ar || reciter.id).join("، ")}`
                : `${toArabicDigits(stoppedReciters.length)} وقفوا هنا`}
              {union ? ` · نحو ${toArabicDigits(union.avg_duration.toFixed(1))}ث` : ""}
              {listenTo ? (
                <>
                  {" · "}
                  <button type="button" className="wq-score-listen" onClick={() => onPlayStop(listenTo.id, wpos)}>
                    استمع
                  </button>
                </>
              ) : null}
            </p>
          ) : (
            <p className="wq-score-empty">
              {data.reciters_total ? "لم يقف قارئ مسجّل في هذا الموضع — وصلوا جميعًا." : "لا توجد تلاوات محلّلة لهذه الآية بعد."}
            </p>
          )}
        </Row>

        <Row id="wq-score-imams" title="أئمة" summary={rulings.length ? `${toArabicDigits(rulings.length)} حكم` : undefined}>
          {rulings.length ? (
            <ul className="m-0 grid list-none gap-2.5 p-0">
              {rulings.map((entry) => {
                const source = classical?.sources[entry.source];
                const meta = classicalGradeMeta[entry.grade];
                const note = (entry.note || "").trim();
                return (
                  <li key={`${entry.source}::${entry.grade}`} className="grid gap-1.5 rounded-lg border border-athar-line-soft bg-athar-surface p-2.5">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className={cn("wq-grade", meta && `is-${meta.cls}`)} title={meta?.desc || entry.grade}>
                        {entry.grade_raw || entry.grade}
                      </span>
                      <span className="text-[0.8rem] font-bold text-athar-ink" title={source ? `${source.title} — ${source.author}` : undefined}>
                        {source?.name || entry.source}
                        {entry.reported_from ? <span className="font-semibold text-athar-ink-faint"> نقلًا عن {entry.reported_from}</span> : null}
                      </span>
                    </span>
                    {/* A quote of only the stop phrase repeats the verse; show it when it adds context. */}
                    {entry.quote && entry.quote.trim().split(/\s+/).length > 4 ? <blockquote className="m-0 font-athar-quran text-[1.02rem] leading-[1.9] text-athar-ink">{entry.quote}</blockquote> : null}
                    {note ? (
                      note.length > NOTE_PREVIEW ? (
                        <details className="wq-illa-more">
                          <summary className="wq-illa">{note.slice(0, NOTE_PREVIEW).trim()}… <b>تتمة العلّة</b></summary>
                          <p className="wq-illa">{note}</p>
                        </details>
                      ) : <p className="wq-illa m-0">{note}</p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="wq-score-empty">لا يتوفر حكم تراثي موثّق لهذا الموضع بعد.</p>
          )}
        </Row>

        <Row id="wq-score-tawjih" title="توجيه" summary={tawjihHere.length ? toArabicDigits(tawjihHere.length) : undefined}>
          {tawjihHere.length ? (
            <div className="grid gap-2.5">
              {tawjihHere.map((entry, position) => (
                <TawjihEntryCard key={`${entry.tweet_id || entry.wpos}-${position}`} entry={entry} words={data.words} author={author} />
              ))}
            </div>
          ) : (
            <p className="wq-score-empty">لا يتوفر توجيه معاصر لهذا الموضع بعد.</p>
          )}
          {tawjihElsewhere > 0 ? (
            <button type="button" className="wq-score-listen w-fit text-[0.76rem]" onClick={onShowAllTawjih}>
              {toArabicDigits(tawjihElsewhere)} توجيه في مواضع أخرى من الآية ←
            </button>
          ) : null}
        </Row>
      </div>
    </div>
  );
}
