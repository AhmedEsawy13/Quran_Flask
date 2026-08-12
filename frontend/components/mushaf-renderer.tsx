import { useEffect, useRef, type CSSProperties } from "react";
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
import { justifyMushafLines } from "@/lib/mushaf-page-layout";
import { tajweedPartsForDisplay, type TajweedSegment } from "@/lib/tajweed";
import { waqfMarkGlyph, waqfMarkLabel, waqfMarkTone } from "@/lib/waqf";

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
  focusRange?: readonly [number, number];
  contextRange?: readonly [number, number];
  concealFocused?: boolean;
  onRetry: () => void;
};

const AYAH_NUMBER_TOKEN = /^\u06dd?[٠-٩]+$/;
const BARE_AYAH_NUMBER_TOKEN = /^[٠-٩]+$/;

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

function wordWaqfMarks(word: MushafWord) {
  if (!Array.isArray(word.waqf_symbols)) return [];
  return word.waqf_symbols.filter((mark) => mark.symbols.trim());
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
  concealFocused,
  editionId,
  tajweedEnabled,
  tajweedSegmentsByWord,
}: {
  line: MushafLine;
  surahNumber: number;
  ayahNumber: number;
  audioPositions: Map<MushafWord, number>;
  activeAudioWord: number | null;
  focusRange?: readonly [number, number];
  contextRange?: readonly [number, number];
  concealFocused?: boolean;
  editionId: MushafEditionId;
  tajweedEnabled?: boolean;
  tajweedSegmentsByWord?: ReadonlyMap<string, TajweedSegment>;
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

  if (line.line_type === "basmallah" || line.line_type === "surah_info") {
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
          ? line.words.map((word, index) => {
              if (word.suppress_render) return null;
              const wordAyah = Number(word.ayah);
              const focused = Number(word.surah) === surahNumber && (
                focusRange
                  ? wordAyah >= focusRange[0] && wordAyah <= focusRange[1]
                  : wordAyah === ayahNumber
              );
              const current = Number(word.surah) === surahNumber && wordAyah === ayahNumber;
              const contextual = Number(word.surah) === surahNumber && Boolean(
                contextRange && wordAyah >= contextRange[0] && wordAyah <= contextRange[1]
              );
              const audioPosition = audioPositions.get(word);
              const audioActive = audioPosition !== undefined && audioPosition === activeAudioWord;
              const waqfMarks = wordWaqfMarks(word);
              const displayText = withAyahOrnament(word.text, editionId);
              const tajweedSegment = tajweedSegmentsByWord?.get(wordIdentity(word));
              const tajweedParts = tajweedEnabled && tajweedSegment && !isAyahNumberToken(displayText)
                ? tajweedPartsForDisplay(displayText, tajweedSegment)
                : null;
              return (
                <span
                  className={`mushaf-word${contextual ? " is-context" : ""}${focused ? " is-focus" : ""}${current ? " is-current" : ""}${focused && concealFocused ? " is-concealed" : ""}${audioActive ? " is-audio-active" : ""}`}
                  key={word.word_key || `${word.word_index ?? "word"}-${index}`}
                  aria-current={current ? "true" : undefined}
                  data-audio-index={audioPosition}
                  data-word-key={word.word_key || undefined}
                >
                  {tajweedParts ? tajweedParts.map((part, partIndex) => part.rule ? (
                    <span className={`tajweed-rule ${part.rule}`} key={`${part.rule}-${partIndex}`}>
                      {part.text}
                    </span>
                  ) : part.text) : displayText}
                  {waqfMarks.map((mark, markIndex) => (
                    <span
                      className={`mushaf-print-mark is-${waqfMarkTone(mark.symbols)}`}
                      aria-label={`${waqfMarkLabel(mark.symbols)} — ${mark.version}`}
                      title={`${waqfMarkLabel(mark.symbols)} · ${mark.version}`}
                      key={`${mark.version}-${mark.symbols}-${markIndex}`}
                    >
                      {waqfMarkGlyph(mark.symbols)}
                    </span>
                  ))}{" "}
                </span>
              );
            })
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
  focusRange,
  contextRange,
  concealFocused,
  onRetry,
}: MushafRendererProps) {
  const pageRef = useRef<HTMLElement>(null);
  const edition = MUSHAF_EDITIONS[editionId];
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
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (active) justifyMushafLines(root, editionId);
      });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    observer?.observe(root);
    fit();
    document.fonts?.ready.then(() => {
      if (active) fit();
    });
    return () => {
      active = false;
      cancelAnimationFrame(frame);
      observer?.disconnect();
    };
  }, [editionId, fontLoading, page, shemrlyAvailable, tajweedEnabled, tajweedLoading, view]);

  return (
    <article
      ref={pageRef}
      className={`reader-page is-${view} edition-${editionId}`}
      aria-busy={isLoading || fontLoading || tajweedLoading}
      data-tajweed={tajweedEnabled ? "true" : undefined}
      style={style}
    >
      <header className="mushaf-head">
        <span className="mushaf-head-juz">
          <span className="mushaf-head-juz-glyph" aria-label={juzName} title={juzName}>
            {juzHeaderGlyph(juzNumber)}
          </span>
        </span>
        <span className="mushaf-head-surahs">
          {pageSurahs.length ? pageSurahs.map((surah) => (
            <span
              className="mushaf-head-surah-glyph"
              aria-label={`سورة ${surah.name}`}
              title={`سورة ${surah.name}`}
              key={surah.number}
            >
              {surahHeaderGlyph(surah.number) || `سورة ${surah.name}`}
            </span>
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
                concealFocused={concealFocused}
                editionId={editionId}
                tajweedEnabled={tajweedEnabled}
                tajweedSegmentsByWord={tajweedSegmentsByWord}
              />
            ))}
          </div>
        ) : (
          <div className="inline-error"><strong>لا يوجد محتوى لهذه الصفحة.</strong></div>
        )}
      </div>

      <footer className="mushaf-foot">
        <span>{edition.label}{fontLoading ? " — يُحمّل الخط…" : ""}</span>
        <span className="page-number">
          {toArabicDigits(view === "page" && page ? page.page_number : ayahNumber)}
        </span>
      </footer>
    </article>
  );
}
