"use client";

import type {WaqfPayload} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {waqfMarkGlyph, waqfMarkLabel, waqfMarkTone} from "@/lib/waqf";
import {ToolCard, ToolCardHead} from "@/components/tool-chrome";
import {StatusState} from "@/components/ui/primitives";

function isNativeAudio(url: string | null | undefined) {
  return Boolean(url && !/youtu(?:\.be|be\.com)/i.test(url));
}

function markOf(mushaf: WaqfPayload["mushafs"][number], wpos: number) {
  return mushaf.marks.find((mark) => mark.wpos === wpos)?.symbol || null;
}

export function WaqfMatrix({
  data,
  playingKey,
  onPlayStop,
  onSelectStop,
}: {
  data: WaqfPayload;
  playingKey: string | null;
  onPlayStop: (reciterId: string, wpos: number) => void;
  onSelectStop: (wpos: number) => void;
}) {
  const columns = [...new Set([
    ...data.union_stops.map((stop) => stop.wpos),
    ...data.mushafs.flatMap((mushaf) => mushaf.marks.map((mark) => mark.wpos)),
  ])].sort((a, b) => a - b);
  const unionByWpos = new Map(data.union_stops.map((stop) => [stop.wpos, stop]));
  const reciterStops = (wpos: number) => data.reciters.some((reciter) =>
    (data.per_reciter[reciter.id]?.stops || []).some((stop) => stop.wpos === wpos),
  );
  const mushafMarked = (wpos: number) => data.mushafs.some((mushaf) => markOf(mushaf, wpos));
  const isStrong = (wpos: number) => {
    const union = unionByWpos.get(wpos);
    return Boolean(union && union.count === data.reciters_total && data.mushafs.length && data.mushafs.every((mushaf) => markOf(mushaf, wpos)));
  };
  const columnClass = (wpos: number) => {
    const union = unionByWpos.get(wpos);
    return [
      isStrong(wpos) ? "is-strong" : "",
      union?.solo ? "is-solo" : "",
      !reciterStops(wpos) ? "is-mushaf-only" : "",
    ].filter(Boolean).join(" ");
  };

  if (!columns.length) {
    return (
      <ToolCard aria-labelledby="waqf-matrix-title">
        <ToolCardHead title="مقارنة القرّاء بمصاحف الوقف" titleId="waqf-matrix-title" />
        <StatusState className="justify-center">لا مواضع وقف مسجّلة لهذه الآية بعد.</StatusState>
      </ToolCard>
    );
  }

  const hasStrong = columns.some(isStrong);
  const hasOnMushaf = data.reciters.some((reciter) =>
    (data.per_reciter[reciter.id]?.stops || []).some((stop) => {
      const union = unionByWpos.get(stop.wpos);
      return union?.solo && mushafMarked(stop.wpos);
    }),
  );

  return (
    <ToolCard aria-labelledby="waqf-matrix-title">
      <ToolCardHead
        title="مقارنة القرّاء بمصاحف الوقف"
        titleId="waqf-matrix-title"
        meta={`${toArabicDigits(columns.length)} موضعًا · ${toArabicDigits(data.mushafs.length)} مصحفًا · ${toArabicDigits(data.reciters.length)} قارئًا`}
      />
      <p className="-mt-1 mb-3 text-[0.88rem] leading-relaxed text-athar-ink-soft">
        الأعمدة مواضع الوقف، والصفوف المصاحف ثم القرّاء. اضغط خلية قارئ لتسمع مقطعه حتى هذا الموضع.
      </p>

      <div className="waqf-matrix-scroll">
        <table className="waqf-matrix">
          <thead>
            <tr>
              <th className="waqf-matrix-name">الموضع ←</th>
              {columns.map((wpos) => {
                const union = unionByWpos.get(wpos);
                return (
                  <th className={columnClass(wpos)} key={wpos}>
                    {isStrong(wpos) ? <div className="waqf-matrix-strong-tag">أقوى وقف</div> : null}
                    <button
                      type="button"
                      className="waqf-matrix-word"
                      onClick={() => onSelectStop(wpos)}
                    >
                      {data.words[wpos] || ""}
                    </button>
                    <div className="waqf-matrix-meta">
                      كلمة {toArabicDigits(wpos + 1)}
                      {union ? ` · ${toArabicDigits(union.count)}/${toArabicDigits(data.reciters_total)}` : ""}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {data.mushafs.map((mushaf) => (
              <tr className="is-mushaf" key={mushaf.id}>
                <th className="waqf-matrix-name" scope="row">{mushaf.name}</th>
                {columns.map((wpos) => {
                  const symbol = markOf(mushaf, wpos);
                  return (
                    <td className={columnClass(wpos)} key={`${mushaf.id}-${wpos}`}>
                      {symbol ? (
                        <span className={`waqf-symbol is-${waqfMarkTone(symbol)}`} title={waqfMarkLabel(symbol)}>
                          {waqfMarkGlyph(symbol)}
                        </span>
                      ) : <span className="waqf-matrix-empty">·</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="is-consensus">
              <th className="waqf-matrix-name" scope="row">اتفاق القرّاء</th>
              {columns.map((wpos) => {
                const union = unionByWpos.get(wpos);
                return (
                  <td className={columnClass(wpos)} key={`consensus-${wpos}`}>
                    {union
                      ? `${toArabicDigits(union.count)}/${toArabicDigits(data.reciters_total)}`
                      : <span className="waqf-matrix-empty">·</span>}
                  </td>
                );
              })}
            </tr>
            {data.reciters.map((reciter) => {
              const detail = data.per_reciter[reciter.id];
              const timeByWpos = new Map((detail?.stops || []).map((stop) => [stop.wpos, stop.time]));
              return (
                <tr key={reciter.id}>
                  <th className="waqf-matrix-name" scope="row">
                    {reciter.name_ar}
                    {detail?.qasr_munfasil ? <small className="waqf-matrix-qasr">قصر المنفصل</small> : null}
                  </th>
                  {columns.map((wpos) => {
                    const time = timeByWpos.get(wpos);
                    const union = unionByWpos.get(wpos);
                    const onMushaf = Boolean(union?.solo && mushafMarked(wpos));
                    const key = `stop:${reciter.id}:${wpos}`;
                    return (
                      <td className={columnClass(wpos)} key={`${reciter.id}-${wpos}`}>
                        {time != null ? (
                          <button
                            type="button"
                            className={`waqf-matrix-play${union?.solo ? " is-solo" : ""}${onMushaf ? " is-on-mushaf" : ""}${playingKey === key ? " is-playing" : ""}`}
                            disabled={!isNativeAudio(detail?.audio_url)}
                            title={onMushaf ? "انفرد بالوقف هنا، ويوافق علامة مطبوعة" : `استمع لـ ${reciter.name_ar}`}
                            aria-label={`استمع لـ ${reciter.name_ar} حتى ${data.words[wpos] || "هذا الموضع"}`}
                            onClick={() => onPlayStop(reciter.id, wpos)}
                          >
                            {playingKey === key ? "Ⅱ" : "▶"} {toArabicDigits(time.toFixed(1))}
                          </button>
                        ) : <span className="waqf-matrix-empty">·</span>}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="waqf-matrix-mobile">
        {columns.map((wpos) => {
          const union = unionByWpos.get(wpos);
          return (
            <article
              className={`waqf-matrix-card${isStrong(wpos) ? " is-strong" : ""}${union?.solo ? " is-solo" : ""}`}
              key={wpos}
            >
              <header>
                <button type="button" className="waqf-matrix-word" onClick={() => onSelectStop(wpos)}>
                  {data.words[wpos] || ""}
                </button>
                <span>كلمة {toArabicDigits(wpos + 1)}</span>
              </header>
              <div className="waqf-matrix-tags">
                {isStrong(wpos) ? <span className="is-strong">أقوى وقف</span> : null}
                {union?.solo ? <span className="is-solo">انفراد</span> : null}
                {union ? <span>{toArabicDigits(union.count)}/{toArabicDigits(data.reciters_total)} قرّاء</span> : null}
              </div>
              {data.mushafs.some((mushaf) => markOf(mushaf, wpos)) ? (
                <div className="waqf-matrix-marks">
                  {data.mushafs.map((mushaf) => {
                    const symbol = markOf(mushaf, wpos);
                    if (!symbol) return null;
                    return (
                      <span key={mushaf.id}>
                        {mushaf.name}
                        <strong className={`is-${waqfMarkTone(symbol)}`}>{waqfMarkGlyph(symbol)}</strong>
                      </span>
                    );
                  })}
                </div>
              ) : null}
              <div className="waqf-matrix-plays">
                {data.reciters.map((reciter) => {
                  const detail = data.per_reciter[reciter.id];
                  const stop = detail?.stops.find((item) => item.wpos === wpos);
                  if (!stop) return null;
                  const key = `stop:${reciter.id}:${wpos}`;
                  return (
                    <button
                      type="button"
                      className={`waqf-matrix-play${playingKey === key ? " is-playing" : ""}`}
                      disabled={!isNativeAudio(detail?.audio_url)}
                      aria-label={`استمع لـ ${reciter.name_ar} حتى ${data.words[wpos] || "هذا الموضع"}`}
                      key={reciter.id}
                      onClick={() => onPlayStop(reciter.id, wpos)}
                    >
                      <span>{reciter.name_ar}</span>
                      <span>{playingKey === key ? "Ⅱ" : "▶"} {toArabicDigits(stop.time.toFixed(1))}</span>
                    </button>
                  );
                })}
              </div>
            </article>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[0.74rem] text-athar-ink-soft">
        {hasStrong ? <span>★ أقوى وقف: كل القرّاء + كل المصاحف</span> : null}
        {hasOnMushaf ? <span>انفراد يوافق علامة مصحف</span> : null}
        {data.mushafs.map((mushaf) => <span key={mushaf.id}>{mushaf.name}</span>)}
      </div>
    </ToolCard>
  );
}
