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
  onSelectWpos,
}: {
  tawjih: TawjihPayload | null;
  words: string[];
  onSelectWpos?: (wpos: number) => void;
}) {
  if (!tawjih?.count || !tawjih.entries.length) return null;

  const author = tawjih.source?.author || "د. أحمد صابر عبدالهادي";
  const profile = tweetHref(tawjih.source?.url) || "https://x.com/Dr_ahmed21";

  return (
    <ToolCard aria-labelledby="waqf-tawjih-title">
      <ToolCardHead
        title="توجيه معاصر — د. أحمد صابر عبدالهادي"
        titleId="waqf-tawjih-title"
        meta={`${toArabicDigits(tawjih.count)} تغريدة مربوطة`}
      />
      <p className="-mt-1 mb-3 text-[0.82rem] text-athar-ink-faint">
        ربط التغريدة بموضع الآية من الاقتباس الصريح —{" "}
        <a className="font-bold text-athar-accent no-underline hover:underline" href={profile} target="_blank" rel="noopener noreferrer">
          {author}
        </a>
      </p>
      <div>
        {tawjih.entries.map((entry, index) => {
          const start = Number.isFinite(entry.wpos_start) ? entry.wpos_start : entry.wpos;
          const phrase = (entry.phrase && entry.phrase.length)
            ? entry.phrase
            : (words.length ? words.slice(Math.max(0, start), entry.wpos + 1) : [entry.stop_word]);
          const meta = entry.grade ? (classicalGradeMeta[entry.grade] || {cls: "kafi", desc: entry.grade}) : null;
          const href = tweetHref(entry.url);
          const body = (entry.note || "").replace(/\s+/g, " ").trim();
          return (
            <article className="wq-tawjih-row" key={`${entry.tweet_id || entry.wpos}-${index}`}>
              <button
                type="button"
                className="wq-tawjih-span"
                onClick={() => onSelectWpos?.(entry.wpos)}
              >
                <span className="wq-tawjih-ref">كلمة {toArabicDigits(entry.wpos + 1)}</span>
                <p className="wq-classical-phrase">
                  {phrase.map((word, wordIndex) => (
                    wordIndex === phrase.length - 1
                      ? <b key={`${entry.wpos}-${wordIndex}`}>{word}</b>
                      : <span key={`${entry.wpos}-${wordIndex}`}>{word} </span>
                  ))}
                </p>
              </button>
              <div className="flex flex-wrap items-baseline gap-2">
                {meta ? (
                  <span className={`wq-grade is-${meta.cls}`} title={meta.desc}>
                    {entry.grade}
                  </span>
                ) : null}
                {href ? (
                  <a className="wq-tawjih-link" href={href} target="_blank" rel="noopener noreferrer">
                    افتح التغريدة
                  </a>
                ) : null}
              </div>
              {body ? <p className="wq-tawjih-note">{body}</p> : null}
            </article>
          );
        })}
      </div>
    </ToolCard>
  );
}
