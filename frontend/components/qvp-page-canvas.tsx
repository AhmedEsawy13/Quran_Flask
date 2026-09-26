"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { canvasPointToPage, loadQvpPage, prefetchQvpPages, type QvpWaqfOverlay } from "@/lib/qvp";
import type { QvpLitePage, QvpView, QvpWord } from "@/lib/qvp-lite";
import { WAQF_GLYPH_REFERENCE_HEIGHT, WaqfGlyph, waqfGlyphSize } from "@/components/ui/waqf-glyph";

type QvpPageCanvasProps = {
  pageNumber: number;
  surahNumber: number;
  ayahNumber: number;
  activeAudioWord?: number | null;
  focusRange?: readonly [number, number];
  concealFocused?: boolean;
  revealedAyahs?: ReadonlySet<number>;
  /** `true` hides every printed sign; a "surah:ayah:word|…" key list hides just those words'. */
  hidePrintedWaqf?: boolean | string;
  waqfOverlays?: QvpWaqfOverlay[];
  onAyahClick?: (surah: number, ayah: number) => void;
  onWordTap?: (surah: number, ayah: number, word: number) => void;
};

function cssColor(name: string, fallback: string) {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}


function hexAlpha(hex: string, alpha: number) {
  const raw = hex.replace("#", "");
  const value = raw.length === 3 ? raw.split("").map((digit) => digit + digit).join("") : raw;
  if (value.length < 6) return `rgba(128, 89, 31, ${alpha})`;
  const red = Number.parseInt(value.slice(0, 2), 16);
  const green = Number.parseInt(value.slice(2, 4), 16);
  const blue = Number.parseInt(value.slice(4, 6), 16);
  if (![red, green, blue].every(Number.isFinite)) return `rgba(128, 89, 31, ${alpha})`;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function highlightIndices(
  page: QvpLitePage,
  surahNumber: number,
  ayahNumber: number,
  focusRange?: readonly [number, number],
  activeAudioWord?: number | null,
) {
  if (activeAudioWord != null) {
    const hit = page.words.find((word) =>
      word.surah === surahNumber
      && word.ayah === ayahNumber
      && word.word === activeAudioWord + 1
    );
    if (hit) return [hit.idx];
  }
  return page.words
    .filter((word) =>
      word.surah === surahNumber && (
        focusRange
          ? word.ayah >= focusRange[0] && word.ayah <= focusRange[1]
          : word.ayah === ayahNumber
      )
    )
    .map((word) => word.idx);
}

function paintPage(
  canvas: HTMLCanvasElement,
  page: QvpLitePage,
  options: {
    surahNumber: number;
    ayahNumber: number;
    activeAudioWord?: number | null;
    focusRange?: readonly [number, number];
    concealFocused?: boolean;
    revealedAyahs?: ReadonlySet<number>;
    hidePrintedWaqf?: boolean | ReadonlySet<number>;
  },
): QvpView {
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(canvas.clientWidth * ratio));
  const height = Math.max(1, Math.floor(canvas.clientHeight * ratio));
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return {scale: 1, x: 0, y: 0};

  const ink = cssColor("--athar-ink", "#231f20");
  const accent = cssColor("--athar-accent", "#176447");
  const band = hexAlpha(cssColor("--athar-gold", "#80591f"), 0.18);
  const view = page.fit(canvas, Math.round(8 * ratio));
  const highlights = highlightIndices(
    page,
    options.surahNumber,
    options.ayahNumber,
    options.focusRange,
    options.activeAudioWord,
  );
  const audioWord = options.activeAudioWord != null
    ? page.words.find((word) =>
      word.surah === options.surahNumber
      && word.ayah === options.ayahNumber
      && word.word === options.activeAudioWord! + 1
    )
    : null;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (options.concealFocused && options.focusRange) {
    const visible = page.words
      .filter((word) => {
        const focused = word.surah === options.surahNumber
          && word.ayah >= options.focusRange![0]
          && word.ayah <= options.focusRange![1];
        if (!focused) return true;
        return Boolean(options.revealedAyahs?.has(word.ayah));
      })
      .map((word) => word.idx);
    ctx.save();
    ctx.setTransform(view.scale, 0, 0, view.scale, view.x, view.y);
    ctx.fillStyle = band;
    for (const index of highlights) {
      const box = page.words[index]?.box;
      if (box) ctx.fillRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
    }
    ctx.restore();
    page.drawDecorations(ctx, {...view, ink, hideWaqf: options.hidePrintedWaqf});
    page.drawWords(ctx, visible, {...view, ink, hideWaqf: options.hidePrintedWaqf});
  } else {
    page.draw(ctx, {...view, ink, highlight: highlights, band, hideWaqf: options.hidePrintedWaqf});
  }
  if (audioWord) page.drawWords(ctx, [audioWord.idx], {...view, ink: accent, hideWaqf: options.hidePrintedWaqf});
  return view;
}

export function QvpPageCanvas({
  pageNumber,
  surahNumber,
  ayahNumber,
  activeAudioWord = null,
  focusRange,
  concealFocused = false,
  revealedAyahs,
  hidePrintedWaqf = false,
  waqfOverlays = [],
  onAyahClick,
  onWordTap,
}: QvpPageCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pageRef = useRef<QvpLitePage | null>(null);
  const viewRef = useRef<QvpView>({scale: 1, x: 0, y: 0});
  const [overlayView, setOverlayView] = useState<QvpView & {dpr: number}>({scale: 1, x: 0, y: 0, dpr: 1});
  const [pageWords, setPageWords] = useState<QvpWord[]>([]);
  const [loadedPage, setLoadedPage] = useState<QvpLitePage | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const requestKey = `${pageNumber}:${retryToken}`;
  const [loadedKey, setLoadedKey] = useState("");
  const [failure, setFailure] = useState<{key: string; message: string} | null>(null);
  const status = failure?.key === requestKey
    ? "error"
    : loadedKey === requestKey
      ? "ready"
      : "loading";
  const error = failure?.key === requestKey ? failure.message : "";

  useEffect(() => {
    let active = true;
    pageRef.current = null;
    loadQvpPage(pageNumber)
      .then((page) => {
        if (!active) return;
        pageRef.current = page;
        setPageWords(page.words);
        setLoadedPage(page);
        setLoadedKey(requestKey);
        prefetchQvpPages(pageNumber);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        pageRef.current = null;
        setPageWords([]);
        setLoadedPage(null);
        setFailure({
          key: requestKey,
          message: reason instanceof Error ? reason.message : "تعذّر تحميل صفحة QVP.",
        });
      });
    return () => {
      active = false;
    };
  }, [pageNumber, requestKey, retryToken]);

  // Each overlay goes in the printed sign's box, or a slot clear of all ink.
  const overlaySlots = useMemo(() => {
    if (!loadedPage) return [];
    // Page units per font unit, from the printed signs: new marks are drawn
    // at the print's own type size, centred where the printed sign (or its
    // clear slot) sits — never squeezed into a differently shaped box.
    const unit = loadedPage.pauseSize.height / WAQF_GLYPH_REFERENCE_HEIGHT;
    return waqfOverlays.flatMap((mark) => {
      const word = pageWords.find((item) => item.surah === mark.surah && item.ayah === mark.ayah && item.word === mark.word);
      if (!word) return [];
      const size = waqfGlyphSize(mark.glyph);
      return [{mark, slot: loadedPage.pauseSlot(word.idx, {width: size.width * unit, height: size.height * unit})}];
    });
  }, [loadedPage, pageWords, waqfOverlays]);

  const hiddenWaqf = useMemo(() => {
    if (typeof hidePrintedWaqf !== "string") return hidePrintedWaqf;
    const keys = new Set(hidePrintedWaqf.split("|").filter(Boolean));
    return new Set(pageWords.filter((word) => keys.has(`${word.surah}:${word.ayah}:${word.word}`)).map((word) => word.idx));
  }, [hidePrintedWaqf, pageWords]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const page = pageRef.current;
    if (!canvas || !page || status !== "ready") return;
    const redraw = () => {
      const view = paintPage(canvas, page, {
        surahNumber, ayahNumber, activeAudioWord, focusRange, concealFocused, revealedAyahs, hidePrintedWaqf: hiddenWaqf,
      });
      viewRef.current = view;
      setOverlayView({...view, dpr: window.devicePixelRatio || 1});
    };
    redraw();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(redraw);
    observer?.observe(canvas);
    return () => observer?.disconnect();
  }, [activeAudioWord, ayahNumber, concealFocused, focusRange, hiddenWaqf, revealedAyahs, status, surahNumber]);

  const handlePointer = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    const page = pageRef.current;
    if (!canvas || !page) return;
    const point = canvasPointToPage(canvas, viewRef.current, clientX, clientY);
    if (!point) return;
    const hit: QvpWord | null = page.hitTest(point.x, point.y);
    if (!hit) return;
    onWordTap?.(hit.surah, hit.ayah, hit.word);
    onAyahClick?.(hit.surah, hit.ayah);
  };

  return (
    <div className="qvp-page-host">
      <canvas
        ref={canvasRef}
        className="qvp-page-canvas"
        aria-label={`صفحة المصحف المطبوع ${pageNumber}`}
        data-word-source="qvp"
        onClick={(event) => handlePointer(event.clientX, event.clientY)}
      />
      {overlaySlots.length && overlayView.scale ? (
        <div className="qvp-waqf-layer" dir="rtl">
          {overlaySlots.map(({mark, slot: [x0, y0, x1, y1]}) => {
            const {scale, x, y, dpr} = overlayView;
            return (
              <span
                className="qvp-pause-slot"
                title={mark.label}
                key={`${mark.surah}:${mark.ayah}:${mark.word}:${mark.glyph}`}
                style={{
                  left: `${(x + x0 * scale) / dpr}px`,
                  top: `${(y + y0 * scale) / dpr}px`,
                  width: `${((x1 - x0) * scale) / dpr}px`,
                  height: `${((y1 - y0) * scale) / dpr}px`,
                }}
              >
                <WaqfGlyph symbol={mark.glyph} fit="box" className="size-full" title={mark.label} />
              </span>
            );
          })}
        </div>
      ) : null}
      {status === "loading" ? (
        <div className="qvp-page-status" aria-label="جارٍ تحميل الرسم المطبوع">
          جارٍ تحميل الصفحة المطبوعة…
        </div>
      ) : null}
      {status === "error" ? (
        <div className="inline-error qvp-page-error">
          <strong>تعذّر تحميل مصحف QVP</strong>
          <span>{error}</span>
          <button type="button" onClick={() => setRetryToken((value) => value + 1)}>أعد المحاولة</button>
        </div>
      ) : null}
    </div>
  );
}
