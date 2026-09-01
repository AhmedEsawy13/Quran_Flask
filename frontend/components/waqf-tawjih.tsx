"use client";

import type {TawjihPayload} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {classicalGradeMeta} from "@/lib/waqf";
import {ToolCard, ToolCardHead} from "@/components/tool-chrome";

function tweetHref(raw: string | null | undefined) {
  try {
    const url = new URL(String(raw || ""));
    if (url.protocol === "https:" && (url.hostname === "x.com" || url.hostname === "www.x.com" || url.hostname === "twitter.com")) {
      return url.href;
    }
  } catch {
    return "";
  }
  return "";
}

export function WaqfTawjih({
  tawjih,
  words,
}: {
  tawjih: TawjihPayload | null;
  words: string[];
}) {
  if (!tawjih?.count || !tawjih.entries.length) return null;

  const author = tawjih.source?.author || "د. أحمد صابر عبدالهادي";
  const profile = tweetHref(tawjih.source?.url) || "https://x.com/Dr_ahmed21";

  return (
    <ToolCard aria-labelledby="waqf-tawjih-title">
      <ToolCardHead
        title="توجيه معاصر — د. أحمد صابر عبدالهادي"
        titleId="waqf-tawjih-title"
        meta={`${toArabicDigits(tawjih.count)} توجيهًا`}
      />
      <p className="-mt-1 mb-3 text-[0.82rem] text-athar-ink-faint">
        {tawjih.source?.title || "توجيه معاصر"} —{" "}
        <a className="font-bold text-athar-accent no-underline hover:underline" href={profile} target="_blank" rel="noopener noreferrer">
          {author}
        </a>
      </p>
      <div>
        {tawjih.entries.map((entry, index) => {
          const stop = (words.length && entry.wpos < words.length) ? words[entry.wpos] : entry.stop_word;
          const meta = entry.grade ? (classicalGradeMeta[entry.grade] || {cls: "kafi", desc: entry.grade}) : null;
          const href = tweetHref(entry.url);
          return (
            <article className="wq-classical-row" key={`${entry.wpos}-${index}`}>
              <p className="wq-classical-phrase"><b>{stop}</b></p>
              <div className="flex flex-wrap items-baseline gap-2">
                {meta ? (
                  <span className={`wq-grade is-${meta.cls}`} title={meta.desc}>
                    {entry.grade}
                  </span>
                ) : null}
                {href ? (
                  <a className="text-[0.78rem] font-bold text-athar-accent no-underline hover:underline" href={href} target="_blank" rel="noopener noreferrer">
                    التغريدة
                  </a>
                ) : null}
              </div>
              {(entry.note || "").trim().length >= 18 ? (
                <details>
                  <summary>التوجيه</summary>
                  <p>{entry.note}</p>
                </details>
              ) : null}
            </article>
          );
        })}
      </div>
    </ToolCard>
  );
}
