"use client";

import type {ReactNode} from "react";
import type {TawjihAttachment, TawjihPayload} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {backendMediaUrl} from "@/lib/paths";
import {classicalGradeMeta} from "@/lib/waqf";
import {ToolCard, ToolCardHead} from "@/components/tool-chrome";

function tweetHref(raw: string | null | undefined) {
  try {
    const url = new URL(String(raw || ""));
    if (url.protocol === "https:" && (url.hostname === "x.com" || url.hostname === "www.x.com" || url.hostname === "twitter.com" || url.hostname === "www.twitter.com")) {
      return url.href;
    }
  } catch {
    return "";
  }
  return "";
}

function safeHttpsHost(raw: string | null | undefined, hosts: Set<string>) {
  try {
    const url = new URL(String(raw || ""));
    if (url.protocol === "https:" && hosts.has(url.hostname)) return url.href;
  } catch {
    return "";
  }
  return "";
}

const VIDEO_HOSTS = new Set(["video.twimg.com"]);
const PROXY_API_RE = /^\/api\/tawjih\/media\/([A-Za-z0-9_-]+)$/;
const PROXY_BACKEND_RE = /^\/backend-api\/tawjih\/media\/([A-Za-z0-9_-]+)$/;

function safeVideoSrc(raw: string | null | undefined): string {
  const src = String(raw || "");
  if (PROXY_API_RE.test(src)) {
    return backendMediaUrl(src) || "";
  }
  if (PROXY_BACKEND_RE.test(src)) {
    return src;
  }
  const https = safeHttpsHost(src, VIDEO_HOSTS);
  if (!https) return "";
  try {
    if (!new URL(https).pathname.toLowerCase().endsWith(".mp4")) return "";
  } catch {
    return "";
  }
  return https;
}

const PHOTO_HOSTS = new Set(["pbs.twimg.com"]);
const YT_HOSTS = new Set(["www.youtube-nocookie.com"]);
const DRIVE_HOSTS = new Set(["drive.google.com", "docs.google.com"]);
const NOTE_HOSTS = new Set([
  "drive.google.com",
  "www.drive.google.com",
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "youtu.be",
  "x.com",
  "www.x.com",
  "twitter.com",
  "www.twitter.com",
]);

function linkifyNote(text: string) {
  const re = /https:\/\/[^\s<>"')\]]+/gi;
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = re.exec(text))) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const raw = match[0];
    const trimmed = raw.replace(/[.,;:!?)»”'"\]]+$/g, "");
    const trailing = raw.slice(trimmed.length);
    const href = safeHttpsHost(trimmed, NOTE_HOSTS);
    nodes.push(
      href ? (
        <a key={`u-${index}`} href={href} target="_blank" rel="noopener noreferrer">
          {trimmed}
        </a>
      ) : (
        trimmed
      ),
    );
    if (trailing) nodes.push(trailing);
    last = match.index + raw.length;
    index += 1;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

function TawjihMedia({
  attachments,
  tweetId,
}: {
  attachments: TawjihAttachment[];
  tweetId?: string;
}) {
  const blocks: ReactNode[] = [];
  const photos: string[] = [];
  const tweetOk = /^[A-Za-z0-9_-]+$/.test(String(tweetId || ""));
  attachments.forEach((att, index) => {
    if (!att?.type) return;
    if (att.type === "video") {
      const src = tweetOk
        ? (backendMediaUrl(`/api/tawjih/media/${tweetId}`) || "")
        : safeVideoSrc(att.src);
      if (!src) return;
      const portrait = Number(att.height) > Number(att.width);
      blocks.push(
        <video
          key={`v-${index}`}
          className={portrait ? "wq-tawjih-video is-portrait" : "wq-tawjih-video"}
          controls
          playsInline
          preload="metadata"
          src={src}
        />,
      );
    } else if (att.type === "youtube") {
      const src = safeHttpsHost(att.embed, YT_HOSTS);
      if (!src || !src.includes("/embed/")) return;
      blocks.push(
        <div className="wq-tawjih-embed" key={`y-${index}`}>
          <iframe src={src} title="فيديو" allow="fullscreen" allowFullScreen loading="lazy" />
        </div>,
      );
    } else if (att.type === "drive") {
      const href = safeHttpsHost(att.href, DRIVE_HOSTS);
      const preview = safeHttpsHost(att.preview, DRIVE_HOSTS);
      const fileId = String(att.file_id || "");
      const thumb = /^[A-Za-z0-9_-]+$/.test(fileId)
        ? `https://lh3.googleusercontent.com/d/${fileId}=w1000`
        : "";
      blocks.push(
        <div className="wq-tawjih-drive" key={`d-${index}`}>
          {thumb ? (
            <img className="wq-tawjih-drive-thumb" src={thumb} alt="" loading="lazy" />
          ) : null}
          {href ? (
            <a className="wq-tawjih-drive-chip" href={href} target="_blank" rel="noopener noreferrer">
              {att.label || "ملف على درايف"}
            </a>
          ) : null}
          {preview && preview.includes("/preview") ? (
            <a className="wq-tawjih-drive-preview" href={preview} target="_blank" rel="noopener noreferrer">
              معاينة
            </a>
          ) : null}
        </div>,
      );
    } else if (att.type === "photo") {
      const src = safeHttpsHost(att.src, PHOTO_HOSTS);
      if (src) photos.push(src);
    }
  });
  if (photos.length) {
    blocks.push(
      <div className="wq-tawjih-photos" key="photos">
        {photos.map((src) => (
          <img key={src} src={src} alt="" loading="lazy" />
        ))}
      </div>,
    );
  }
  if (!blocks.length) return null;
  return <div className="wq-tawjih-media">{blocks}</div>;
}

export function TawjihEntryCard({
  entry,
  words,
  author,
  onSelectWpos,
}: {
  entry: TawjihPayload["entries"][number];
  words: string[];
  author: string;
  onSelectWpos?: (wpos: number) => void;
}) {
  const start = Number.isFinite(entry.wpos_start) ? entry.wpos_start : entry.wpos;
  const phrase = (entry.phrase && entry.phrase.length)
    ? entry.phrase
    : (words.length ? words.slice(Math.max(0, start), entry.wpos + 1) : [entry.stop_word]);
  const meta = entry.grade ? (classicalGradeMeta[entry.grade] || {cls: "kafi", desc: entry.grade}) : null;
  const href = tweetHref(entry.url);
  const body = entry.display_note ?? entry.note ?? "";
  const questionHref = tweetHref(entry.question_url);
  return (
    <article className="wq-tawjih-card">
      <header className="wq-tawjih-head">
        <button
          type="button"
          className="wq-tawjih-span"
          onClick={() => onSelectWpos?.(entry.wpos)}
        >
          <p className="wq-tawjih-phrase">
            {phrase.map((word, wordIndex) => (
              wordIndex === phrase.length - 1
                ? <b key={`${entry.wpos}-${wordIndex}`}>{word}</b>
                : <span key={`${entry.wpos}-${wordIndex}`}>{word} </span>
            ))}
          </p>
        </button>
        <div className="wq-tawjih-head-meta">
          {meta ? (
            <span className={`wq-grade is-${meta.cls}`} title={meta.desc}>
              {entry.grade}
            </span>
          ) : null}
          <span className="wq-tawjih-ref">كلمة {toArabicDigits(entry.wpos + 1)}</span>
        </div>
      </header>
      <TawjihMedia attachments={entry.attachments || []} tweetId={entry.tweet_id} />
      {typeof entry.question === "string" && entry.question.trim() ? (
        <div className="wq-tawjih-qa">
          <div className="wq-tawjih-q">
            <p className="wq-tawjih-qa-kicker">
              سؤال
              {entry.question_author ? (
                <>
                  {" · "}
                  {questionHref ? (
                    <a href={questionHref} target="_blank" rel="noopener noreferrer">
                      {entry.question_author}
                    </a>
                  ) : (
                    entry.question_author
                  )}
                </>
              ) : null}
            </p>
            <p className="wq-tawjih-qa-text">{linkifyNote(entry.question)}</p>
          </div>
          <div className="wq-tawjih-a">
            <p className="wq-tawjih-qa-kicker">جواب · د. أحمد صابر عبدالهادي</p>
            <p className="wq-tawjih-qa-text">{linkifyNote(entry.answer || entry.display_note || entry.note || body)}</p>
          </div>
        </div>
      ) : body ? (
        <p className="wq-tawjih-note">{linkifyNote(body)}</p>
      ) : null}
      <footer className="wq-tawjih-foot">
        <span className="wq-tawjih-author">{author}</span>
        {href ? (
          <a className="wq-tawjih-link" href={href} target="_blank" rel="noopener noreferrer">
            افتح التغريدة
          </a>
        ) : null}
      </footer>
    </article>
  );
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

  return (
    <ToolCard aria-labelledby="waqf-tawjih-title">
      <ToolCardHead
        title="توجيه معاصر — د. أحمد صابر عبدالهادي"
        titleId="waqf-tawjih-title"
        meta={`${toArabicDigits(tawjih.count)} تغريدة مربوطة`}
      />
      <p className="-mt-1 mb-3 text-[0.82rem] text-athar-ink-faint">
        وقفه وتوجيهه، ومعه المقطع أو الملف إن وُجد.
      </p>
      <div className="flex flex-col gap-3.5">
        {tawjih.entries.map((entry, index) => (
          <TawjihEntryCard
            key={`${entry.tweet_id || entry.wpos}-${index}`}
            entry={entry}
            words={words}
            author={author}
            onSelectWpos={onSelectWpos}
          />
        ))}
      </div>
    </ToolCard>
  );
}
