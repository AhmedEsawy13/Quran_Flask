"use client";

import {useMemo, useState} from "react";
import type {WaqfPayload} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {reciterPhrases, waqfMarkGlyph, waqfMarkLabel} from "@/lib/waqf";
import {ToolCard, ToolCardHead} from "@/components/tool-chrome";
import {StatusState} from "@/components/ui/primitives";

function isNativeAudio(url: string | null | undefined) {
  return Boolean(url && !/youtu(?:\.be|be\.com)/i.test(url));
}

export function WaqfReciters({
  data,
  playingKey,
  onPlayPhrase,
}: {
  data: WaqfPayload;
  playingKey: string | null;
  onPlayPhrase: (reciterId: string, phraseIndex: number) => void;
}) {
  const lastWpos = Math.max(0, data.words.length - 1);
  const mushafPos = useMemo(
    () => new Set(data.mushafs.flatMap((mushaf) => mushaf.marks.map((mark) => mark.wpos))),
    [data],
  );
  const markByWpos = useMemo(() => {
    const marks = new Map<number, string>();
    ["المدينة الجديد", "المدينة القديم", "الشمرلي", "الأزهر", "قطر", "الكويت", "البحرين"].forEach((id) => {
      const mushaf = data.mushafs.find((item) => item.id === id);
      mushaf?.marks.forEach((mark) => {
        if (!marks.has(mark.wpos)) marks.set(mark.wpos, mark.symbol);
      });
    });
    data.mushafs.forEach((mushaf) => {
      mushaf.marks.forEach((mark) => {
        if (!marks.has(mark.wpos)) marks.set(mark.wpos, mark.symbol);
      });
    });
    return marks;
  }, [data]);
  const soloSet = useMemo(
    () => new Set(data.union_stops.filter((stop) => stop.solo).map((stop) => stop.wpos)),
    [data],
  );
  const groups = useMemo(() => {
    const bySig = new Map<string, string[]>();
    const order: string[] = [];
    data.reciters.forEach((reciter) => {
      const detail = data.per_reciter[reciter.id];
      if (!detail) return;
      const sig = reciterPhrases(detail, lastWpos).map((phrase) => `${phrase.first_wpos}-${phrase.last_wpos}`).join(",");
      const members = bySig.get(sig);
      if (members) members.push(reciter.id);
      else {
        bySig.set(sig, [reciter.id]);
        order.push(sig);
      }
    });
    return order
      .map((sig) => bySig.get(sig) || [])
      .sort((a, b) => b.length - a.length);
  }, [data, lastWpos]);

  if (!groups.length) {
    return (
      <ToolCard aria-labelledby="waqf-reciters-title">
        <ToolCardHead title="كيف قرأها كل قارئ" titleId="waqf-reciters-title" />
        <StatusState className="justify-center">لا يتوفر تفصيل قرّاء لهذه الآية بعد.</StatusState>
      </ToolCard>
    );
  }

  return (
    <ToolCard aria-labelledby="waqf-reciters-title">
      <ToolCardHead
        title="كيف قرأها كل قارئ"
        titleId="waqf-reciters-title"
        meta={`${toArabicDigits(data.reciters.length)} قارئًا · يُجمع من قرأ بنفس المواضع في صف واحد`}
      />
      <p className="-mt-1 mb-3 text-[0.88rem] leading-relaxed text-athar-ink-soft">
        تختلف الأزمنة بين القرّاء تبعًا لأدائهم (قصر المدّ المنفصل يجعل القراءة أسرع)؛ الزمن المعروض هو مدّة كل مقطع.
      </p>
      <div className="grid gap-3">
        {groups.map((members) => (
          <ReciterGroup
            data={data}
            key={members.join("-")}
            lastWpos={lastWpos}
            markByWpos={markByWpos}
            members={members}
            mushafPos={mushafPos}
            onPlayPhrase={onPlayPhrase}
            playingKey={playingKey}
            soloSet={soloSet}
          />
        ))}
      </div>
    </ToolCard>
  );
}

function ReciterGroup({
  data,
  lastWpos,
  markByWpos,
  members,
  mushafPos,
  onPlayPhrase,
  playingKey,
  soloSet,
}: {
  data: WaqfPayload;
  lastWpos: number;
  markByWpos: Map<number, string>;
  members: string[];
  mushafPos: Set<number>;
  onPlayPhrase: (reciterId: string, phraseIndex: number) => void;
  playingKey: string | null;
  soloSet: Set<number>;
}) {
  const preferred = members.includes(data.ref_reciter || "") ? data.ref_reciter || members[0] : members[0];
  const [activeId, setActiveId] = useState(preferred);
  const detail = data.per_reciter[activeId];
  if (!detail) return null;
  const phrases = reciterPhrases(detail, lastWpos);
  const durations = members.map((id) => data.per_reciter[id]?.duration || 0);
  const minD = Math.round(Math.min(...durations));
  const maxD = Math.round(Math.max(...durations));
  const onMushaf = (detail.stops || []).filter((stop) => mushafPos.has(stop.wpos)).length;
  const nStops = detail.stops.length;
  const nReps = detail.repeats.length;

  return (
    <article className="wq-reciter-group">
      <header className="wq-reciter-head">
        {members.length === 1 ? (
          <strong>{detail.name_ar}</strong>
        ) : (
          <div className="wq-reciter-names">
            {members.map((id) => {
              const reciter = data.per_reciter[id];
              return (
                <button
                  type="button"
                  className={`wq-reciter-chip${id === activeId ? " is-active" : ""}`}
                  key={id}
                  onClick={() => setActiveId(id)}
                >
                  {reciter?.name_ar || id}
                </button>
              );
            })}
          </div>
        )}
        {detail.qasr_munfasil ? <span className="wq-qasr">قصر المنفصل</span> : null}
        <span className="wq-reciter-stats">
          <span><b>{toArabicDigits(nStops)}</b> {nStops === 1 ? "وقفة" : "وقفات"}</span>
          {mushafPos.size ? (
            <span>موافقة المصحف <b>{toArabicDigits(onMushaf)}/{toArabicDigits(nStops)}</b></span>
          ) : null}
          {nReps ? <span><b>{toArabicDigits(nReps)}</b> {nReps === 1 ? "إعادة" : "إعادات"}</span> : null}
          <span>{minD === maxD ? `~${toArabicDigits(minD)}ث` : `~${toArabicDigits(minD)}–${toArabicDigits(maxD)}ث`}</span>
          {members.length > 1 ? (
            <span>{toArabicDigits(members.length)}/{toArabicDigits(data.reciters_total)}</span>
          ) : null}
        </span>
      </header>

      {detail.solo_stops_detail?.length ? (
        <div className="wq-solo-detail">
          <strong className="text-[0.78rem] text-athar-gold">انفرد بالوقف {toArabicDigits(detail.solo_stops_detail.length)}</strong>
          <div className="wq-solo-items">
            {detail.solo_stops_detail.map((item) => (
              <div className="wq-solo-item" key={`${item.wpos}-${item.time}`}>
                <span className="font-athar-quran">{item.word || "موضع"}</span>
                <span>{toArabicDigits(item.time.toFixed(1))}ث</span>
                {item.mushaf_matches?.length
                  ? item.mushaf_matches.map((match) => (
                    <small key={`${match.mushaf}-${match.symbol}`}>يوافق {match.mushaf} {match.symbol}</small>
                  ))
                  : <small>بلا علامة مطبوعة</small>}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="waqf-segment-list" aria-label={`مقاطع ${detail.name_ar}`}>
        {phrases.map((phrase, index) => {
          const key = `gallery:${activeId}:${index}`;
          const active = playingKey === key;
          const isLast = index === phrases.length - 1;
          const symbol = markByWpos.get(phrase.last_wpos);
          return (
            <button
              type="button"
              className={active ? "is-playing" : ""}
              disabled={!isNativeAudio(detail.audio_url)}
              key={key}
              onClick={() => onPlayPhrase(activeId, index)}
            >
              <span className="waqf-segment-number">{toArabicDigits(index + 1)}</span>
              <span className="waqf-segment-words">
                {data.words.slice(phrase.first_wpos, phrase.last_wpos + 1).join(" ")}
              </span>
              <span className="waqf-segment-time">
                {active ? "Ⅱ" : "▶"} {toArabicDigits((phrase.end - phrase.start).toFixed(1))}ث
                {isLast ? " · رأس الآية" : symbol ? ` · ${waqfMarkLabel(symbol)} ${waqfMarkGlyph(symbol)}` : ""}
                {!isLast && soloSet.has(phrase.last_wpos) ? " · انفرد" : ""}
              </span>
            </button>
          );
        })}
      </div>
    </article>
  );
}
