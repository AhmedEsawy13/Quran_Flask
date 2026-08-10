import type { CSSProperties } from "react";
import type { Ayah, MushafLine, MushafPage, Surah } from "@/lib/api";
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
  onRetry: () => void;
};

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
}: {
  line: MushafLine;
  surahNumber: number;
  ayahNumber: number;
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
            return (
              <span
                className={`mushaf-word${focused ? " is-focus" : ""}`}
                key={word.word_key || `${word.word_index ?? "word"}-${index}`}
                aria-current={focused ? "true" : undefined}
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
  onRetry,
}: MushafRendererProps) {
  const edition = MUSHAF_EDITIONS[editionId];
  const style = {
    "--reader-quran-font": edition.fontFamily,
  } as CSSProperties;
  const pageSurahs = page ? collectSurahNames(page, surahs) : "";

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
            <p className="quran-text reader-verse">{ayah.text}</p>
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
