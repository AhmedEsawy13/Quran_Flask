import type { MushafPage, MushafWord } from "@/lib/api";
import { loadPage, type QvpLitePage, type QvpWord } from "@/lib/qvp-lite";
import { waqfMarkCanonical, waqfMarkGlyph, waqfMarkLabel, waqfMarkTone } from "@/lib/waqf";

const AYAH_NUMBER_TOKEN = /^\u06dd?[٠-٩]+$/;

/** Must match data/qvp_upstream.json pages.release. Bump both after a CDN data release. */
export const QVP_RELEASE = "v0.5.0";
export const QVP_CDN_HOST = "https://cdn.quran.ws/qvp";
export const QVP_CDN = `${QVP_CDN_HOST}/${QVP_RELEASE}`;
export const QVP_PAGE_ASPECT = 345 / 550;

const cache = new Map<number, Promise<QvpLitePage>>();

export function qvpPageUrl(pageNumber: number) {
  const safe = Math.min(604, Math.max(1, Math.trunc(pageNumber)));
  return `${QVP_CDN}/${String(safe).padStart(3, "0")}.qvp`;
}

export function loadQvpPage(pageNumber: number, signal?: AbortSignal) {
  const safe = Math.min(604, Math.max(1, Math.trunc(pageNumber)));
  let pending = cache.get(safe);
  if (!pending) {
    pending = loadPage(qvpPageUrl(safe), signal ? {signal} : undefined);
    cache.set(safe, pending);
    pending.catch(() => {
      cache.delete(safe);
    });
  }
  return pending;
}

/** Which print a QVP page comes from: the quran.ws Madinah CDN, or Athar's own الشمرلي beta pages. */
export type QvpSource = "madinah" | "shamarly";

const shamarlyCache = new Map<number, Promise<QvpLitePage>>();
let shamarlyPagesPending: Promise<ReadonlySet<number>> | null = null;

/**
 * Beta: الشمرلي pages drawn with the vector PDF's own outlines (pipeline/paw_split/shamarly_qvp_svg.py
 * → quran-engine svg2qvp), served by Flask. An empty set where the server has none.
 */
export function loadShamarlyQvpPageSet() {
  if (!shamarlyPagesPending) {
    shamarlyPagesPending = fetch("/backend-api/shamarly/qvp-pages")
      .then((response) => (response.ok ? response.json() : {pages: []}))
      .then((data: {pages?: number[]}) => new Set(Array.isArray(data.pages) ? data.pages : []) as ReadonlySet<number>)
      .catch(() => new Set<number>());
  }
  return shamarlyPagesPending;
}

const shamarlyTajweedCache = new Map<number, Promise<Record<string, string[]> | null>>();

/** Beta: {word key: tajweed class of each coloured mark path of the word, in path order}; null when the page has none. */
export function loadShamarlyTajweed(pageNumber: number) {
  const safe = Math.max(1, Math.trunc(pageNumber));
  let pending = shamarlyTajweedCache.get(safe);
  if (!pending) {
    pending = fetch(`/backend-api/shamarly/qvp-tajweed/${String(safe).padStart(3, "0")}.json`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data: Record<string, string[]> | null) => (data && typeof data === "object" ? data : null))
      .catch(() => null);
    shamarlyTajweedCache.set(safe, pending);
  }
  return pending;
}

export function loadShamarlyQvpPage(pageNumber: number) {
  const safe = Math.max(1, Math.trunc(pageNumber));
  let pending = shamarlyCache.get(safe);
  if (!pending) {
    pending = loadPage(`/backend-api/shamarly/qvp/${String(safe).padStart(3, "0")}.qvp`);
    shamarlyCache.set(safe, pending);
    pending.catch(() => {
      shamarlyCache.delete(safe);
    });
  }
  return pending;
}

export function prefetchQvpPages(pageNumber: number) {
  for (const neighbor of [pageNumber - 1, pageNumber + 1]) {
    if (neighbor >= 1 && neighbor <= 604) void loadQvpPage(neighbor);
  }
}

export function qvpWordKey(word: QvpWord) {
  return `${word.surah}:${word.ayah}:${word.word}`;
}

export type QvpWaqfOverlay = {
  surah: number;
  ayah: number;
  word: number;
  glyph: string;
  tone: string;
  label: string;
};

function wordWaqfEntries(word: MushafWord, waqfSource: string) {
  if (!Array.isArray(word.waqf_symbols)) return [];
  return word.waqf_symbols.filter((mark) => mark.version === waqfSource && mark.symbols.trim());
}

/** The mushaf the QVP pages were printed from; its marks are already in the ink. */
export const QVP_PRINTED_WAQF_SOURCE = "المدينة الجديد";

/**
 * Page query for a QVP page: the chosen mushaf's marks plus the printed
 * one's, so each word can be compared and left alone where they agree.
 */
export function qvpVersionQuery(waqfSource: string) {
  const versions = [...new Set([waqfSource, QVP_PRINTED_WAQF_SOURCE].filter(Boolean))];
  return `?${versions.map((version) => `mushaf_version=${encodeURIComponent(version)}`).join("&")}`;
}

export type QvpWaqfPlan = {
  /** Signs to draw: only where the chosen mushaf differs from the print. */
  overlays: QvpWaqfOverlay[];
  /** Words (surah:ayah:word) whose printed sign must be hidden. */
  replaced: Set<string>;
};

function canonicalMarks(symbols: string | undefined) {
  return (symbols || "").split(/[،,]/).map((token) => waqfMarkCanonical(token)).filter(Boolean).sort().join(",");
}

/**
 * Compare the chosen mushaf with the printed one word by word. Where they
 * agree the printed sign stays untouched; where they differ the printed sign
 * is hidden and the chosen one drawn in its place.
 */
export function qvpWaqfPlan(page: MushafPage | null, waqfSource: string): QvpWaqfPlan {
  const plan: QvpWaqfPlan = {overlays: [], replaced: new Set()};
  if (!page) return plan;
  const counts = new Map<string, number>();
  page.lines.forEach((line) => {
    line.words.forEach((word) => {
      if (word.suppress_render || AYAH_NUMBER_TOKEN.test((word.text || "").trim())) return;
      const surah = Number(word.surah);
      const ayah = Number(word.ayah);
      if (!Number.isInteger(surah) || !Number.isInteger(ayah) || surah < 1 || ayah < 1) return;
      const verse = `${surah}:${ayah}`;
      const next = (counts.get(verse) || 0) + 1;
      counts.set(verse, next);
      const chosen = wordWaqfEntries(word, waqfSource)[0];
      const printed = wordWaqfEntries(word, QVP_PRINTED_WAQF_SOURCE)[0];
      if (canonicalMarks(chosen?.symbols) === canonicalMarks(printed?.symbols)) return;
      plan.replaced.add(`${verse}:${next}`);
      if (!chosen) return;
      plan.overlays.push({
        surah,
        ayah,
        word: next,
        glyph: waqfMarkGlyph(chosen.symbols),
        tone: waqfMarkTone(chosen.symbols),
        label: `${waqfMarkLabel(chosen.symbols)} · ${chosen.version}`,
      });
    });
  });
  return plan;
}

export function canvasPointToPage(
  canvas: HTMLCanvasElement,
  view: {scale: number; x: number; y: number},
  clientX: number,
  clientY: number,
) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height || !view.scale) return null;
  const canvasX = (clientX - rect.left) * (canvas.width / rect.width);
  const canvasY = (clientY - rect.top) * (canvas.height / rect.height);
  return {
    x: (canvasX - view.x) / view.scale,
    y: (canvasY - view.y) / view.scale,
  };
}
