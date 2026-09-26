"use client";

import type {ClassicalWaqfPayload} from "@/lib/api";
import {arabicCount} from "@/lib/mushaf";
import {ImamRulings} from "@/components/imam-rulings";
import {ToolCard, ToolCardHead} from "@/components/tool-chrome";
import {StatusState} from "@/components/ui/primitives";

export function WaqfClassical({
  classical,
  words,
  onSelectWpos,
}: {
  classical: ClassicalWaqfPayload | null;
  words: string[];
  onSelectWpos?: (wpos: number) => void;
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
    byPos.set(entry.wpos, [...(byPos.get(entry.wpos) || []), entry]);
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
        meta={`${arabicCount(classical.count, ["حكم واحد", "حكمان", "أحكام", "حكمًا"])} · ${arabicCount(positions.length, ["موضع واحد", "موضعان", "مواضع", "موضعًا"])}`}
      />
      {sources ? <p className="-mt-1 mb-3 text-[0.82rem] text-athar-ink-faint">{sources}</p> : null}
      <div>
        {rows.map(({wpos, list, phrase}) => (
          <article className="wq-classical-row" key={wpos}>
            <button
              type="button"
              className="wq-classical-phrase block w-full cursor-pointer rounded-md border-0 bg-transparent p-0 text-start font-[inherit] text-inherit hover:bg-athar-accent/5"
              title="اعرض هذا الموضع في لوحة التفصيل"
              onClick={() => onSelectWpos?.(wpos)}
            >
              {phrase.map((word, index) => (
                index === phrase.length - 1
                  ? <b key={`${wpos}-${index}`}>{word}</b>
                  : <span key={`${wpos}-${index}`}>{word} </span>
              ))}
            </button>
            <ImamRulings entries={list} sources={classical.sources} showQuote={false} />
          </article>
        ))}
      </div>
    </ToolCard>
  );
}
