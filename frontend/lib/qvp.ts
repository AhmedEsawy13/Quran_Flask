import type { MushafPage, MushafWord } from "@/lib/api";
import { loadPage, type QvpLitePage, type QvpWord } from "@/lib/qvp-lite";
import { waqfMarkGlyph, waqfMarkLabel, waqfMarkTone } from "@/lib/waqf";

const AYAH_NUMBER_TOKEN = /^\u06dd?[٠-٩]+$/;

/** Must match data/qvp_upstream.json pages.release. Bump both after a CDN data release. */
export const QVP_RELEASE = "v0.3.0";
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

export function qvpWaqfOverlaysFromPage(page: MushafPage | null, waqfSource: string): QvpWaqfOverlay[] {
  if (!page) return [];
  const counts = new Map<string, number>();
  const overlays: QvpWaqfOverlay[] = [];
  page.lines.forEach((line) => {
    line.words.forEach((word) => {
      if (word.suppress_render || AYAH_NUMBER_TOKEN.test((word.text || "").trim())) return;
      const surah = Number(word.surah);
      const ayah = Number(word.ayah);
      if (!Number.isInteger(surah) || !Number.isInteger(ayah) || surah < 1 || ayah < 1) return;
      const key = `${surah}:${ayah}`;
      const next = (counts.get(key) || 0) + 1;
      counts.set(key, next);
      const mark = wordWaqfEntries(word, waqfSource)[0];
      if (!mark) return;
      overlays.push({
        surah,
        ayah,
        word: next,
        glyph: waqfMarkGlyph(mark.symbols),
        tone: waqfMarkTone(mark.symbols),
        label: `${waqfMarkLabel(mark.symbols)} · ${mark.version}`,
      });
    });
  });
  return overlays;
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
