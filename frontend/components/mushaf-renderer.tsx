import type { CSSProperties } from "react";
import type { Ayah, MushafLine, MushafPage, MushafWord, Surah } from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  juzLabelForPage,
  toArabicDigits,
  type MushafEditionId,
  type ReaderView,
} from "@/lib/mushaf";

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
  onRetry: () => void;
};

const AYAH_NUMBER_TOKEN = /^\u06dd?[٠-٩]+$/;

function isAyahNumberToken(text: string) {
  return AYAH_NUMBER_TOKEN.test(text.trim());
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

function collectSurahNames(page: MushafPage, surahs: Surah[]) {
  const numbers = new Set<number>();
  page.lines.forEach((line) => {
    const lineSurah = Number(line.surah_number);
    if (Number.isInteger(lineSurah) && lineSurah > 0) numbers.add(lineSurah);
    line.words.forEach((word) => numbers.add(Number(word.surah)));
  });
  if (!numbers.size && page.anchor_surah_number) numbers.add(page.anchor_surah_number);
  return [...numbers]
    .map((number) => surahs.find((surah) => surah.number === number)?.name)
    .filter(Boolean)
    .join(" · ");
}

function PageLine({
  line,
  surahNumber,
  ayahNumber,
  audioPositions,
  activeAudioWord,
}: {
  line: MushafLine;
  surahNumber: number;
  ayahNumber: number;
  audioPositions: Map<MushafWord, number>;
  activeAudioWord: number | null;
}) {
  if (line.line_type === "surah_name") {
    return <div className="mushaf-surah-banner">{line.display_text}</div>;
  }

  if (line.line_type === "basmallah" || line.line_type === "surah_info") {
    return <div className="mushaf-special-line">{line.display_text}</div>;
  }

  return (
    <div
      className={`mushaf-line${line.is_centered ? " is-centered" : ""}`}
      data-focus={line.contains_focus_ayah ? "true" : undefined}
    >
      {line.words.length
        ? line.words.map((word, index) => {
            if (word.suppress_render) return null;
            const focused =
              Number(word.surah) === surahNumber && Number(word.ayah) === ayahNumber;
            const audioPosition = audioPositions.get(word);
            const audioActive = audioPosition !== undefined && audioPosition === activeAudioWord;
            return (
              <span
                className={`mushaf-word${focused ? " is-focus" : ""}${audioActive ? " is-audio-active" : ""}`}
                key={word.word_key || `${word.word_index ?? "word"}-${index}`}
                aria-current={focused ? "true" : undefined}
                data-audio-index={audioPosition}
              >
                {word.text}{" "}
              </span>
            );
          })
        : line.display_text}
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
  onRetry,
}: MushafRendererProps) {
  const edition = MUSHAF_EDITIONS[editionId];
  const style = {
    "--reader-quran-font": edition.fontFamily,
  } as CSSProperties;
  const pageSurahs = page ? collectSurahNames(page, surahs) : "";
  const pageAudioPositions = buildPageAudioPositions(page, surahNumber, ayahNumber);

  return (
    <article
      className={`reader-page is-${view}`}
      aria-busy={isLoading || fontLoading}
      style={style}
    >
      <header className="mushaf-head">
        <span>
          {view === "page" && page ? juzLabelForPage(page.page_number) : edition.shortLabel}
        </span>
        <span>
          {pageSurahs || (selectedSurah ? `سورة ${selectedSurah.name}` : "المصحف")}
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
