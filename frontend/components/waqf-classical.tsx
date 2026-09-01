"use client";

import type {ClassicalWaqfPayload} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {classicalGradeMeta} from "@/lib/waqf";
import {ToolCard, ToolCardHead} from "@/components/tool-chrome";
import {StatusState} from "@/components/ui/primitives";

export function WaqfClassical({
  classical,
  words,
}: {
  classical: ClassicalWaqfPayload | null;
  words: string[];
}) {
  if (!classical?.count) {
    return (
      <ToolCard aria-labelledby="waqf-classical-all-title">
        <ToolCardHead title="لماذا يُوقف هنا؟ — كتب الوقف والابتداء" titleId="waqf-classical-all-title" />
        <StatusState className="justify-center">لا يتوفر حكم تراثي موثّق لهذه الآية بعد.</StatusState>
      </ToolCard>
    );
  }

  const byPos = new Map<number, typeof classical.entries>();
  classical.entries.forEach((entry) => {
    const list = byPos.get(entry.wpos) || [];
    if (!list.some((item) => item.source === entry.source && item.grade === entry.grade)) {
      list.push(entry);
      byPos.set(entry.wpos, list);
    }
  });
  const positions = [...byPos.keys()].sort((a, b) => a - b);
  const sources = Object.values(classical.sources).map((source) => `${source.title} — ${source.author}`).join(" · ");
  const rows = positions.map((wpos, index) => {
    const prev = index === 0 ? -1 : positions[index - 1];
    const start = Math.max(prev + 1, wpos - 12, 0);
    const list = byPos.get(wpos) || [];
    const phrase = words.length && wpos < words.length
      ? words.slice(start, wpos + 1)
      : [list[0]?.stop_word || ""];
    return {wpos, list, phrase};
  });

  return (
    <ToolCard aria-labelledby="waqf-classical-all-title">
      <ToolCardHead
        title="لماذا يُوقف هنا؟ — كتب الوقف والابتداء"
        titleId="waqf-classical-all-title"
        meta={`${toArabicDigits(classical.count)} حكمًا · ${toArabicDigits(positions.length)} موضعًا`}
      />
      {sources ? <p className="-mt-1 mb-3 text-[0.82rem] text-athar-ink-faint">{sources}</p> : null}
      <div>
        {rows.map(({wpos, list, phrase}) => (
          <article className="wq-classical-row" key={wpos}>
            <p className="wq-classical-phrase">
              {phrase.map((word, index) => (
                index === phrase.length - 1
                  ? <b key={`${wpos}-${index}`}>{word}</b>
                  : <span key={`${wpos}-${index}`}>{word} </span>
              ))}
            </p>
            <div className={`wq-rulings${list.length > 1 ? " has-split" : ""}`}>
              {list.map((entry, index) => {
                const meta = classicalGradeMeta[entry.grade] || {cls: "kafi", desc: entry.grade};
                const source = classical.sources[entry.source];
                const attrib = entry.reported_from
                  ? `${source?.name || entry.source} نقلًا عن ${entry.reported_from}`
                  : source?.name || entry.source;
                const note = (entry.note || "").trim();
                const preview = note.length > 280 ? `${note.slice(0, 280).trim()}…` : note;
                return (
                  <div className="wq-ruling" key={`${entry.source}-${entry.grade}-${index}`}>
                    <span className={`wq-grade is-${meta.cls}`} title={meta.desc}>
                      {entry.grade_raw || entry.grade}
                      <small>· {attrib}</small>
                    </span>
                    {preview ? <p className="wq-illa">{preview}</p> : null}
                    {note.length > 280 ? (
                      <details className="wq-illa-more">
                        <summary>تتمة العلّة</summary>
                        <p>{note}</p>
                      </details>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </article>
        ))}
      </div>
    </ToolCard>
  );
}
