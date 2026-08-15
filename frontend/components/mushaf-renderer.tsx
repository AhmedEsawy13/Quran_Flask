import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";
import type { Ayah, MushafLine, MushafPage, MushafWord, Surah } from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  juzHeaderGlyph,
  juzLabel,
  juzNumberForPage,
  juzNumberFromAyah,
  surahHeaderGlyph,
  toArabicDigits,
  type MushafEditionId,
  type ReaderView,
} from "@/lib/mushaf";
import { fitAndJustifyMushafPage } from "@/lib/mushaf-page-layout";
import { tajweedPartsForDisplay, type TajweedSegment } from "@/lib/tajweed";
import type { TopicWash } from "@/lib/topic-color";
import { waqfMarkGlyph, waqfMarkLabel, waqfMarkTone } from "@/lib/waqf";

export type PracticeTap = {
  surah: number;
  fromAyah: number;
  toAyah: number;
  stopKeys: ReadonlySet<string>;
  positions: WeakMap<MushafWord, number>;
  lastWpos: ReadonlyMap<number, number>;
  onWordTap: (ayah: number, wpos: number) => void;
};

type MushafRendererProps = {
  view: ReaderView;
  editionId: MushafEditionId;
  ayah: Ayah | null;
  page: MushafPage | null;
  surahs: Surah[];
  selectedSurah: Surah | undefined;
  surahNumber: number;
  ayahNumber: number;
  isLoading: boolean;
  error: string;
  fontLoading: boolean;
  activeAudioWord: number | null;
  tajweedEnabled?: boolean;
  tajweedLoading?: boolean;
  tajweedSegmentsByWord?: ReadonlyMap<string, TajweedSegment>;
  waqfEnabled?: boolean;
  waqfSource?: string;
  dualLayout?: boolean;
  memorizationMode?: boolean;
  practice?: PracticeTap | null;
  focusRange?: readonly [number, number];
  contextRange?: readonly [number, number];
  contextByKey?: ReadonlyMap<string, TopicWash>;
  concealFocused?: boolean;
  draftAyah?: number | null;
  picking?: boolean;
  revealedAyahs?: ReadonlySet<number>;
  onAyahClick?: (surah: number, ayah: number) => void;
  onSurahNavigate?: (surah: number) => void;
  onJuzNavigate?: (juz: number) => void;
  onPageNavigate?: (page: number) => void;
  onRetry: () => void;
};

const AYAH_NUMBER_TOKEN = /^\u06dd?[٠-٩]+$/;
const BARE_AYAH_NUMBER_TOKEN = /^[٠-٩]+$/;
const EMBEDDED_WAQF_RE = /[\u06D6-\u06DC]/g;

function isAyahNumberToken(text: string) {
  return AYAH_NUMBER_TOKEN.test(text.trim());
}

function withAyahOrnament(text: string, editionId: MushafEditionId) {
  const trimmed = text.trim();
  if (editionId === "shamarly" || !BARE_AYAH_NUMBER_TOKEN.test(trimmed)) return text;
  return `۝${trimmed}`;
}

function wordIdentity(word: MushafWord) {
  if (word.word_key) return word.word_key;
  return Number.isFinite(Number(word.word_index)) ? `#${word.word_index}` : "";
}

function verseKeyOf(word: MushafWord) {
  const surah = Number(word.surah);
  const ayah = Number(word.ayah);
  if (!Number.isInteger(surah) || !Number.isInteger(ayah) || surah < 1 || ayah < 1) return "";
  return `${surah}:${ayah}`;
}

function paintContextBands(root: HTMLElement) {
  const linesRoot = root.querySelector<HTMLElement>(".mushaf-lines");
  const layer = root.querySelector<HTMLElement>(".mz-context-layer");
  if (!linesRoot || !layer) return;
  layer.replaceChildren();
  const words = [...linesRoot.querySelectorAll<HTMLElement>(".mushaf-word.is-context[data-context-color]")];
  if (!words.length) return;
  const origin = layer.parentElement || linesRoot;
  const rootRect = origin.getBoundingClientRect();
  if (!rootRect.width || !rootRect.height) return;
  const scale = rootRect.width / Math.max(1, origin.offsetWidth);

  const byLine = new Map<HTMLElement, Map<string, {color: string; words: HTMLElement[]}>>();
  words.forEach((word) => {
    const line = word.closest<HTMLElement>(".mushaf-line");
    const color = word.dataset.contextColor;
    const segmentId = word.dataset.contextSegment;
    if (!line || !color) return;
    const groupKey = `${segmentId || ""}|${color}`;
    if (!byLine.has(line)) byLine.set(line, new Map());
    const groups = byLine.get(line);
    if (!groups) return;
    if (!groups.has(groupKey)) groups.set(groupKey, {color, words: []});
    groups.get(groupKey)?.words.push(word);
  });

  byLine.forEach((groups) => {
    groups.forEach(({color, words: lineWords}) => {
      const rects = lineWords
        .map((word) => word.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0);
      if (!rects.length) return;
      const left = Math.min(...rects.map((rect) => rect.left));
      const right = Math.max(...rects.map((rect) => rect.right));
      const top = Math.min(...rects.map((rect) => rect.top));
      const bottom = Math.max(...rects.map((rect) => rect.bottom));
      const padX = 3;
      const padY = 1;
      const band = document.createElement("div");
      band.className = "mz-context-band";
      band.style.setProperty("--mz-band-color", color);
      band.style.left = `${(left - rootRect.left) / scale - padX}px`;
      band.style.top = `${(top - rootRect.top) / scale - padY}px`;
      band.style.width = `${Math.max(0, (right - left) / scale + padX * 2)}px`;
      band.style.height = `${Math.max(0, (bottom - top) / scale + padY * 2)}px`;
      layer.appendChild(band);
    });
  });
}

function paintSelectionBands(root: HTMLElement) {
  const linesRoot = root.querySelector<HTMLElement>(".mushaf-lines");
  const layer = root.querySelector<HTMLElement>(".mz-selection-layer");
  if (!linesRoot || !layer) return;
  layer.replaceChildren();
  const words = [...linesRoot.querySelectorAll<HTMLElement>(
    ".mushaf-word.is-focus[data-surah][data-ayah]",
  )];
  if (!words.length) return;
  const origin = layer.parentElement || linesRoot;
  const rootRect = origin.getBoundingClientRect();
  if (!rootRect.width || !rootRect.height) return;
  const scale = rootRect.width / Math.max(1, origin.offsetWidth);

  const byLine = new Map<HTMLElement, Map<string, HTMLElement[]>>();
  words.forEach((word) => {
    const line = word.closest<HTMLElement>(".mushaf-line");
    const verseKey = `${word.dataset.surah}:${word.dataset.ayah}`;
    if (!line) return;
    if (!byLine.has(line)) byLine.set(line, new Map());
    const groups = byLine.get(line);
    if (!groups) return;
    if (!groups.has(verseKey)) groups.set(verseKey, []);
    groups.get(verseKey)?.push(word);
  });

  byLine.forEach((groups) => {
    groups.forEach((lineWords, verseKey) => {
      const rects = lineWords
        .map((word) => word.getBoundingClientRect())
        .filter((rect) => rect.width > 0 && rect.height > 0);
      if (!rects.length) return;
      const left = Math.min(...rects.map((rect) => rect.left));
      const right = Math.max(...rects.map((rect) => rect.right));
      const top = Math.min(...rects.map((rect) => rect.top));
      const bottom = Math.max(...rects.map((rect) => rect.bottom));
      const band = document.createElement("div");
      const current = lineWords.some((word) => word.classList.contains("is-current"));
      const draft = lineWords.some((word) => word.classList.contains("is-range-draft"));
      band.className = `mz-selection-band${current ? " is-current" : ""}${draft ? " is-draft" : ""}`;
      band.dataset.verse = verseKey;
      band.dataset.ayah = verseKey.split(":")[1];
      band.style.left = `${(left - rootRect.left) / scale - 3}px`;
      band.style.top = `${(top - rootRect.top) / scale - 1}px`;
      band.style.width = `${Math.max(0, (right - left) / scale + 6)}px`;
      band.style.height = `${Math.max(0, (bottom - top) / scale + 2)}px`;
      layer.appendChild(band);
    });
  });
}

function wordWaqfMarks(word: MushafWord) {
  if (!Array.isArray(word.waqf_symbols)) return [];
  return word.waqf_symbols.filter((mark) => mark.symbols.trim());
}

function wordDisplayText(
  word: MushafWord,
  editionId: MushafEditionId,
  waqfEnabled: boolean,
  waqfSource: string,
) {
  const raw = word.text || "";
  if (editionId === "shamarly") return withAyahOrnament(raw, editionId);
  const clean = raw.replace(EMBEDDED_WAQF_RE, "");
  if (!waqfEnabled) return withAyahOrnament(clean, editionId);
  if (waqfSource === "المدينة الجديد") return withAyahOrnament(raw, editionId);
  const selectedMark = wordWaqfMarks(word).find((mark) => mark.version === waqfSource);
  return withAyahOrnament(
    clean + (selectedMark ? waqfMarkGlyph(selectedMark.symbols) : ""),
    editionId,
  );
}

function buildPageAudioPositions(page: MushafPage | null, surah: number, ayah: number) {
  const positions = new Map<MushafWord, number>();
  let position = 0;
  page?.lines.forEach((line) => {
    line.words.forEach((word) => {
      if (
        !word.suppress_render && Number(word.surah) === surah &&
        Number(word.ayah) === ayah && !isAyahNumberToken(word.text)
      ) {
        positions.set(word, position);
        position += 1;
      }
    });
  });
  return positions;
}

function collectPageSurahs(page: MushafPage, surahs: Surah[]) {
  const numbers = new Set<number>();
  page.lines.forEach((line) => {
    const lineSurah = Number(line.surah_number);
    if (Number.isInteger(lineSurah) && lineSurah > 0) numbers.add(lineSurah);
    line.words.forEach((word) => numbers.add(Number(word.surah)));
  });
  if (!numbers.size && page.anchor_surah_number) numbers.add(page.anchor_surah_number);
  return [...numbers]
    .map((number) => ({
      number,
      name: surahs.find((surah) => surah.number === number)?.name || toArabicDigits(number),
    }));
}

function firstPageVerse(page: MushafPage, fallbackSurah: number, fallbackAyah: number) {
  for (const line of page.lines) {
    for (const word of line.words) {
      const surah = Number(word.surah);
      const ayah = Number(word.ayah);
      if (Number.isInteger(surah) && Number.isInteger(ayah) && surah > 0 && ayah > 0) {
        return {surah, ayah};
      }
    }
  }
  return {
    surah: Number(page.anchor_surah_number) || fallbackSurah,
    ayah: fallbackAyah,
  };
}

function PageLine({
  line,
  surahNumber,
  ayahNumber,
  audioPositions,
  activeAudioWord,
  focusRange,
  contextRange,
  contextByKey,
  concealFocused,
  draftAyah,
  picking,
  revealedAyahs,
  practice,
  onAyahClick,
  editionId,
  tajweedEnabled,
  tajweedSegmentsByWord,
  waqfEnabled,
  waqfSource,
  selectableWaqf,
}: {
  line: MushafLine;
  surahNumber: number;
  ayahNumber: number;
  audioPositions: Map<MushafWord, number>;
  activeAudioWord: number | null;
  focusRange?: readonly [number, number];
  contextRange?: readonly [number, number];
  contextByKey?: ReadonlyMap<string, TopicWash>;
  concealFocused?: boolean;
  draftAyah?: number | null;
  picking?: boolean;
  revealedAyahs?: ReadonlySet<number>;
  practice?: PracticeTap | null;
  onAyahClick?: (surah: number, ayah: number) => void;
  editionId: MushafEditionId;
  tajweedEnabled?: boolean;
  tajweedSegmentsByWord?: ReadonlyMap<string, TajweedSegment>;
  waqfEnabled: boolean;
  waqfSource: string;
  selectableWaqf: boolean;
}) {
  if (line.line_type === "surah_name") {
    const lineSurahNumber = Number(line.surah_number);
    const glyph = surahHeaderGlyph(lineSurahNumber);
    return (
      <div
        className={`mushaf-surah-banner${glyph ? " has-glyph" : ""}`}
        aria-label={line.display_text || `سورة ${toArabicDigits(lineSurahNumber)}`}
      >
        {glyph || line.display_text}
      </div>
    );
  }

  if (line.line_type === "basmallah") {
    return (
      <div className="mushaf-line is-centered">
        <div
          className="mushaf-basmala-glyph"
          aria-label={line.display_text || "بسم الله الرحمن الرحيم"}
        >
          {"\u00F3"}
        </div>
      </div>
    );
  }

  if (line.line_type === "surah_info") {
    return <div className="mushaf-special-line">{line.display_text}</div>;
  }

  return (
    <div
      className={`mushaf-line${line.is_centered ? " is-centered" : ""}`}
      data-justify={line.is_centered ? undefined : "true"}
      data-focus={line.contains_focus_ayah ? "true" : undefined}
    >
      <div className="mushaf-line-inner">
        {line.words.length
          ? (() => {
              let appended = 0;
              return line.words.flatMap((word, index) => {
              if (word.suppress_render) return [];
              const wordAyah = Number(word.ayah);
              const focused = Number(word.surah) === surahNumber && (
                focusRange
                  ? wordAyah >= focusRange[0] && wordAyah <= focusRange[1]
                  : wordAyah === ayahNumber
              );
              const current = Number(word.surah) === surahNumber && wordAyah === ayahNumber;
              const draft = Number(word.surah) === surahNumber && draftAyah != null && wordAyah === draftAyah;
              const revealed = Boolean(revealedAyahs?.has(wordAyah));
              const concealed = Boolean(concealFocused && !revealed);
              const wash = contextByKey?.get(verseKeyOf(word));
              const contextual = Boolean(wash) || (
                Number(word.surah) === surahNumber && Boolean(
                  contextRange && wordAyah >= contextRange[0] && wordAyah <= contextRange[1]
                )
              );
              const audioPosition = audioPositions.get(word);
              const audioActive = audioPosition !== undefined && audioPosition === activeAudioWord;
              const waqfMarks = waqfEnabled && (!selectableWaqf || editionId === "shamarly")
                ? wordWaqfMarks(word)
                : [];
              const displayText = selectableWaqf
                ? wordDisplayText(word, editionId, waqfEnabled, waqfSource)
                : withAyahOrnament(word.text, editionId);
              const tajweedSegment = tajweedSegmentsByWord?.get(wordIdentity(word));
              const tajweedParts = tajweedEnabled && tajweedSegment && !isAyahNumberToken(displayText)
                ? tajweedPartsForDisplay(displayText, tajweedSegment)
                : null;
              const practiceWpos = practice?.positions.get(word);
              const practiceInRange = Boolean(
                practice
                && practiceWpos != null
                && Number(word.surah) === practice.surah
                && wordAyah >= practice.fromAyah
                && wordAyah <= practice.toAyah,
              );
              const practiceStopped = Boolean(practiceInRange && practice && practice.stopKeys.has(`${wordAyah}:${practiceWpos}`));
              const practiceEnd = Boolean(practiceInRange && practice && practice.lastWpos.get(wordAyah) === practiceWpos);
              const practiceCtx = Boolean(practice && !practiceInRange && practiceWpos != null);
              // Match تثبيت: space BETWEEN word spans (not inside), so word-spacing justify works.
              const nodes: ReactNode[] = [];
              if (appended > 0) nodes.push(" ");
              appended += 1;
              nodes.push(
                <span
                  className={`mushaf-word${contextual ? " is-context" : ""}${focused && !practice ? " is-focus" : ""}${current && !practice ? " is-current" : ""}${draft ? " is-range-draft" : ""}${concealed ? " is-concealed" : ""}${revealed ? " is-revealed" : ""}${audioActive ? " is-audio-active" : ""}${picking || concealFocused || practiceInRange ? " is-interactive" : ""}${practiceInRange ? " practice-word" : ""}${practiceStopped ? " is-stopped" : ""}${practiceEnd ? " is-end" : ""}${practiceCtx ? " is-practice-ctx" : ""}`}
                  key={word.word_key || `${word.word_index ?? "word"}-${index}`}
                  role={practiceInRange ? "button" : undefined}
                  tabIndex={practiceInRange ? 0 : undefined}
                  aria-pressed={practiceInRange ? practiceStopped : undefined}
                  aria-current={current ? "true" : undefined}
                  aria-label={practiceInRange
                    ? (practiceStopped ? `إلغاء الوقف عند ${displayText}` : `تعليم وقف عند ${displayText}`)
                    : undefined}
                  data-audio-index={audioPosition}
                  data-word-key={word.word_key || undefined}
                  data-surah={Number.isInteger(Number(word.surah)) ? String(word.surah) : undefined}
                  data-ayah={Number.isInteger(wordAyah) ? String(wordAyah) : undefined}
                  data-wpos={practiceWpos != null ? String(practiceWpos) : undefined}
                  data-context-color={wash?.color}
                  data-context-segment={wash ? String(wash.segmentId) : undefined}
                  style={wash ? {"--mz-topic": wash.color} as CSSProperties : undefined}
                  onClick={practiceInRange && practice && practiceWpos != null
                    ? () => practice.onWordTap(wordAyah, practiceWpos)
                    : onAyahClick ? () => {
                      const surah = Number(word.surah);
                      const ayah = Number(word.ayah);
                      if (!Number.isInteger(surah) || !Number.isInteger(ayah) || surah < 1 || ayah < 1) return;
                      onAyahClick(surah, ayah);
                    } : undefined}
                  onKeyDown={practiceInRange && practice && practiceWpos != null
                    ? (event) => {
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      practice.onWordTap(wordAyah, practiceWpos);
                    }
                    : undefined}
                >
                  {tajweedParts ? tajweedParts.map((part, partIndex) => part.rule ? (
                    <span className={`tajweed-rule ${part.rule}`} key={`${part.rule}-${partIndex}`}>
                      {part.text}
                    </span>
                  ) : part.text) : displayText}
                  {waqfMarks.length ? (
                    <span className="mushaf-waqf-stack">
                      {waqfMarks.map((mark, markIndex) => (
                        <span
                          className={`mushaf-print-mark is-${waqfMarkTone(mark.symbols)}`}
                          aria-label={`${waqfMarkLabel(mark.symbols)} — ${mark.version}`}
                          title={`${waqfMarkLabel(mark.symbols)} · ${mark.version}`}
                          data-version={mark.version}
                          key={`${mark.version}-${mark.symbols}-${markIndex}`}
                        >
                          {waqfMarkGlyph(mark.symbols)}
                        </span>
                      ))}
                    </span>
                  ) : null}
                </span>,
              );
              return nodes;
            });
            })()
          : line.display_text}
      </div>
    </div>
  );
}

export function MushafRenderer({
  view,
  editionId,
  ayah,
  page,
  surahs,
  selectedSurah,
  surahNumber,
  ayahNumber,
  isLoading,
  error,
  fontLoading,
  activeAudioWord,
  tajweedEnabled = false,
  tajweedLoading = false,
  tajweedSegmentsByWord,
  waqfEnabled = true,
  waqfSource,
  dualLayout = false,
  memorizationMode = false,
  practice = null,
  focusRange,
  contextRange,
  contextByKey,
  concealFocused,
  draftAyah = null,
  picking = false,
  revealedAyahs,
  onAyahClick,
  onSurahNavigate,
  onJuzNavigate,
  onPageNavigate,
  onRetry,
}: MushafRendererProps) {
  const pageRef = useRef<HTMLElement>(null);
  const edition = MUSHAF_EDITIONS[editionId];
  const selectableWaqf = waqfSource !== undefined;
  const activeWaqfSource = waqfSource || edition.waqfSource;
  const focusRangeStart = focusRange?.[0];
  const focusRangeEnd = focusRange?.[1];
  const shemrlyAvailable = editionId !== "shamarly" || page?.glyph_mapping_mode === "shemrly-page-local";
  const quranFont = editionId === "shamarly" && shemrlyAvailable && page?.font_name
    ? `"${page.font_name}", "Uthmanic Hafs", serif`
    : edition.fontFamily;
  const style = {
    "--reader-quran-font": quranFont,
  } as CSSProperties;
  const pageSurahs = page
    ? collectPageSurahs(page, surahs)
    : selectedSurah ? [{number: selectedSurah.number, name: selectedSurah.name}] : [];
  const pageAudioPositions = buildPageAudioPositions(page, surahNumber, ayahNumber);
  const firstVerse = page
    ? firstPageVerse(page, surahNumber, ayahNumber)
    : {surah: surahNumber, ayah: ayahNumber};
  const juzNumber = view === "page" && page && editionId !== "azhar_amiri" && editionId !== "shamarly"
    ? juzNumberForPage(page.page_number)
    : juzNumberFromAyah(firstVerse.surah, firstVerse.ayah);
  const juzName = juzLabel(juzNumber);

  useEffect(() => {
    if (activeAudioWord === null) return;
    const activeWord = pageRef.current?.querySelector<HTMLElement>(
      `[data-audio-index="${activeAudioWord}"]`,
    );
    if (!activeWord) return;
    const rect = activeWord.getBoundingClientRect();
    const safeInset = Math.min(120, window.innerHeight * 0.18);
    if (rect.top >= safeInset && rect.bottom <= window.innerHeight - safeInset) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    activeWord.scrollIntoView({
      block: "center",
      inline: "nearest",
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [activeAudioWord, view, page?.page_number, ayah?.verse_key]);

  useEffect(() => {
    const root = pageRef.current;
    if (!root || view !== "page" || !page || !shemrlyAvailable || fontLoading) return;
    let frame = 0;
    let active = true;
    let sameSizePasses = 0;
    let lastSize = "";
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (!active) return;
        // Same pipeline as تثبيت: measured font size, then capped line justify.
        fitAndJustifyMushafPage(root, editionId, { dual: dualLayout });
        paintContextBands(root);
        paintSelectionBands(root);
      });
    };
    const observer = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(() => {
        if (!active) return;
        const nextSize = `${root.clientWidth}x${root.clientHeight}`;
        if (nextSize !== lastSize) {
          lastSize = nextSize;
          sameSizePasses = 0;
          fit();
          return;
        }
        // Same-size storms (font shaping / zoom) — bound like تثبيت.
        if (sameSizePasses >= 4) return;
        sameSizePasses += 1;
        fit();
      });
    observer?.observe(root);
    fit();
    document.fonts?.ready.then(() => {
      if (!active) return;
      sameSizePasses = 0;
      lastSize = "";
      fit();
    });
    return () => {
      active = false;
      cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [activeWaqfSource, ayahNumber, contextByKey, draftAyah, dualLayout, editionId, focusRangeEnd, focusRangeStart, fontLoading, memorizationMode, page, practice?.fromAyah, practice?.toAyah, shemrlyAvailable, tajweedEnabled, tajweedLoading, view, waqfEnabled]);

  return (
    <article
      ref={pageRef}
      className={`reader-page is-${view} edition-${editionId}${memorizationMode ? " is-memorization" : ""}${practice ? " is-practice" : ""}${picking ? " is-picking" : ""}${concealFocused ? " is-concealed" : ""}`}
      aria-busy={isLoading || fontLoading || tajweedLoading}
      data-tajweed={tajweedEnabled ? "true" : undefined}
      data-waqf-enabled={waqfEnabled ? "true" : "false"}
      data-waqf-source={activeWaqfSource}
      data-picking={picking ? "true" : undefined}
      style={style}
    >
      <header className="mushaf-head">
        <span className="mushaf-head-juz">
          {onJuzNavigate ? (
            <button
              type="button"
              className="mushaf-head-action mushaf-head-juz-glyph"
              aria-label={`اختر الجزء — ${juzName}`}
              title={`الانتقال إلى جزء آخر · ${juzName}`}
              onClick={() => onJuzNavigate(juzNumber)}
            >
              {juzHeaderGlyph(juzNumber)}
            </button>
          ) : (
            <span className="mushaf-head-juz-glyph" aria-label={juzName} title={juzName}>
              {juzHeaderGlyph(juzNumber)}
            </span>
          )}
        </span>
        <span className="mushaf-head-surahs">
          {pageSurahs.length ? pageSurahs.map((surah) => (
            onSurahNavigate ? (
              <button
                type="button"
                className="mushaf-head-action mushaf-head-surah-glyph"
                aria-label={`اختر السورة — سورة ${surah.name}`}
                title={`الانتقال إلى سورة أخرى · ${surah.name}`}
                key={surah.number}
                onClick={() => onSurahNavigate(surah.number)}
              >
                {surahHeaderGlyph(surah.number) || `سورة ${surah.name}`}
              </button>
            ) : (
              <span
                className="mushaf-head-surah-glyph"
                aria-label={`سورة ${surah.name}`}
                title={`سورة ${surah.name}`}
                key={surah.number}
              >
                {surahHeaderGlyph(surah.number) || `سورة ${surah.name}`}
              </span>
            )
          )) : <span>المصحف</span>}
        </span>
      </header>

      <div className="reader-page-body" aria-live="polite">
        {isLoading ? (
          <div className="verse-skeleton reader-skeleton" aria-label="جارٍ تحميل المصحف">
            <span />
            <span />
            <span />
          </div>
        ) : error ? (
          <div className="inline-error">
            <strong>لم تصل الصفحة</strong>
            <span>{error}</span>
            <button type="button" onClick={onRetry}>أعد المحاولة</button>
          </div>
        ) : view === "verse" && ayah ? (
          <div className="reader-verse-view">
            <p className="quran-text reader-verse">
              {ayah.text.trim().split(/\s+/).map((word, index, words) => {
                const audioPosition = isAyahNumberToken(word) ? null : index;
                return (
                  <span
                    className={`reader-verse-word${audioPosition !== null && audioPosition === activeAudioWord ? " is-audio-active" : ""}`}
                    data-audio-index={audioPosition ?? undefined}
                    key={`${ayah.verse_key}-${index}`}
                  >
                    {word}{index < words.length - 1 ? " " : ""}
                  </span>
                );
              })}
            </p>
            {ayah.transliteration?.t ? (
              <details className="transliteration">
                <summary>النقل الصوتي</summary>
                <p dir="ltr">{ayah.transliteration.t}</p>
              </details>
            ) : null}
          </div>
        ) : view === "page" && page && !shemrlyAvailable ? (
          <div className="inline-error px-5">
            <strong>خط الشمرلي غير متوفر لهذه الصفحة بعد</strong>
            <span>خط الشمرلي مستخرج صفحةً صفحة؛ اختر رسمًا آخر هنا، أو افتح آية من الصفحات المكتملة.</span>
            <a
              className="rounded-lg border border-athar-line px-3 py-1.5 text-xs font-bold text-athar-accent no-underline hover:border-athar-accent"
              href="/read?surah=11&ayah=121&view=page&edition=shamarly"
            >
              شاهد صفحة مكتملة من الشمرلي
            </a>
          </div>
        ) : view === "page" && page ? (
          <div className="mushaf-lines-host">
            {contextByKey ? <div className="mz-context-layer" aria-hidden="true" /> : null}
            {memorizationMode && focusRange ? <div className="mz-selection-layer" aria-hidden="true" /> : null}
            <div className="mushaf-lines" aria-label={`صفحة ${page.page_number}`}>
              {page.lines.map((line) => (
                <PageLine
                  key={`${page.page_number}-${line.line_number}`}
                  line={line}
                  surahNumber={surahNumber}
                  ayahNumber={ayahNumber}
                  audioPositions={pageAudioPositions}
                  activeAudioWord={activeAudioWord}
                  focusRange={focusRange}
                  contextRange={contextRange}
                  contextByKey={contextByKey}
                  concealFocused={concealFocused}
                  draftAyah={draftAyah}
                  picking={picking}
                  revealedAyahs={revealedAyahs}
                  practice={practice}
                  onAyahClick={onAyahClick}
                  editionId={editionId}
                  tajweedEnabled={tajweedEnabled}
                  tajweedSegmentsByWord={tajweedSegmentsByWord}
                  waqfEnabled={waqfEnabled}
                  waqfSource={activeWaqfSource}
                  selectableWaqf={selectableWaqf}
                />
              ))}
            </div>
          </div>
        ) : (
          <div className="inline-error"><strong>لا يوجد محتوى لهذه الصفحة.</strong></div>
        )}
      </div>

      <footer className="mushaf-foot">
        <span>{edition.label}{fontLoading ? " — يُحمّل الخط…" : ""}</span>
        {view === "page" && page && onPageNavigate ? (
          <button
            type="button"
            className="page-number"
            aria-label={`اختر الصفحة — الصفحة ${toArabicDigits(page.page_number)}`}
            title="الانتقال إلى صفحة أخرى"
            onClick={() => onPageNavigate(page.page_number)}
          >
            {toArabicDigits(page.page_number)}
          </button>
        ) : (
          <span className="page-number">
            {toArabicDigits(view === "page" && page ? page.page_number : ayahNumber)}
          </span>
        )}
      </footer>
    </article>
  );
}
