"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  getJson,
  getJsonAccepting,
  type MemorizationContext,
  type MushafPage,
  type Surah,
} from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  isMushafEdition,
  toArabicDigits,
  type MushafEditionId,
} from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { useEditionFont } from "@/lib/use-edition-font";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { MemorizePlayer } from "@/components/memorize-player";
import {
  Button,
  Field,
  HandoffSurface,
  ProgressBar,
  SelectControl,
  StatTile,
  StatusState,
  Surface,
} from "@/components/ui/primitives";

type PageResult = {
  key: string;
  page: MushafPage | null;
  error: string;
};

type ContextResult = {
  key: string;
  data: MemorizationContext | null;
};

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function MemorizeWorkspace() {
  const searchParams = useSearchParams();
  const initialSurah = Math.min(114, positiveInteger(searchParams.get("surah"), 2));
  const initialFrom = positiveInteger(searchParams.get("from"), positiveInteger(searchParams.get("ayah"), 255));
  const initialTo = Math.max(initialFrom, positiveInteger(searchParams.get("to"), initialFrom));
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(initialSurah);
  const [fromAyah, setFromAyah] = useState(initialFrom);
  const [toAyah, setToAyah] = useState(initialTo);
  const [activeAyah, setActiveAyah] = useState(initialFrom);
  const [editionId, setEditionId] = useState<MushafEditionId>(() => {
    const value = searchParams.get("edition");
    return isMushafEdition(value) ? value : "digital_khatt";
  });
  const [concealed, setConcealed] = useState(false);
  const [activeAudioWord, setActiveAudioWord] = useState<number | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [retryToken, setRetryToken] = useState(0);
  const [pageResult, setPageResult] = useState<PageResult>({key: "", page: null, error: ""});
  const [contextResult, setContextResult] = useState<ContextResult>({key: "", data: null});
  const edition = MUSHAF_EDITIONS[editionId];
  const pageKey = `${editionId}:${surahNumber}:${activeAyah}:${retryToken}`;
  const contextKey = `${surahNumber}:${activeAyah}:${retryToken}`;
  const visiblePage = pageResult.key === pageKey ? pageResult : null;
  const pageFontName = editionId === "shamarly" && visiblePage?.page?.glyph_mapping_mode === "shemrly-page-local"
    ? visiblePage.page.font_name
    : undefined;
  const fontLoading = useEditionFont(editionId, pageFontName);
  const visibleContext = contextResult.key === contextKey ? contextResult.data : null;
  const contextLoading = contextResult.key !== contextKey;
  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const rangeLength = Math.max(1, toAyah - fromAyah + 1);
  const contextRange = visibleContext?.found && visibleContext.from?.surah === surahNumber && visibleContext.to?.surah === surahNumber
    ? [visibleContext.from.ayah, visibleContext.to.ayah] as const
    : undefined;
  const contextPosition = contextRange
    ? Math.max(1, Math.min(contextRange[1] - contextRange[0] + 1, activeAyah - contextRange[0] + 1))
    : 1;
  const contextLength = contextRange ? contextRange[1] - contextRange[0] + 1 : Math.max(1, visibleContext?.run_length || 1);
  const updateActiveAyah = useCallback((ayah: number) => {
    setActiveAyah(ayah);
    setActiveAudioWord(null);
  }, []);

  const loadAyahNumbers = useCallback(async (surah: number, signal?: AbortSignal) => {
    const cached = ayahCache.current.get(surah);
    if (cached) return cached;
    const numbers = await getJson<number[]>(`/backend-api/surahs/${surah}/ayahs`, signal);
    ayahCache.current.set(surah, numbers);
    return numbers;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Surah[]>("/backend-api/surahs", controller.signal)
      .then((items) => {
        setSurahs(items);
        setCatalogError("");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تحميل قائمة السور.");
      });
    return () => controller.abort();
  }, [retryToken]);

  useEffect(() => {
    const controller = new AbortController();
    loadAyahNumbers(surahNumber, controller.signal)
      .then((numbers) => {
        setAyahNumbers(numbers);
        if (!numbers.length) return;
        const last = numbers[numbers.length - 1];
        const nextFrom = Math.min(Math.max(1, fromAyah), last);
        const nextTo = Math.min(Math.max(nextFrom, toAyah), last);
        setFromAyah(nextFrom);
        setToAyah(nextTo);
        setActiveAyah((current) => current >= nextFrom && current <= nextTo ? current : nextFrom);
        setActiveAudioWord(null);
        setCatalogError("");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAyahNumbers([]);
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تحميل آيات السورة.");
      });
    return () => controller.abort();
  }, [surahNumber, retryToken, loadAyahNumbers, fromAyah, toAyah]);

  useEffect(() => {
    const controller = new AbortController();
    const usesExplicitMarks = editionId === "azhar_amiri" || editionId === "shamarly";
    getJson<MushafPage>(
      `/backend-api/${edition.apiBase}/page-by-ayah/${surahNumber}/${activeAyah}${usesExplicitMarks ? `?mushaf_version=${encodeURIComponent(edition.waqfSource)}` : ""}`,
      controller.signal,
    )
      .then((page) => setPageResult({key: pageKey, page, error: ""}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setPageResult({
          key: pageKey,
          page: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل صفحة التثبيت.",
        });
      });
    return () => controller.abort();
  }, [edition.apiBase, edition.waqfSource, editionId, surahNumber, activeAyah, retryToken, pageKey]);

  useEffect(() => {
    const controller = new AbortController();
    getJsonAccepting<MemorizationContext>(
      `/backend-api/memorization/context/${surahNumber}/${activeAyah}`,
      [404],
      controller.signal,
    )
      .then((data) => setContextResult({key: contextKey, data}))
      .catch(() => setContextResult({key: contextKey, data: null}));
    return () => controller.abort();
  }, [surahNumber, activeAyah, retryToken, contextKey]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("from", String(fromAyah));
    url.searchParams.set("to", String(toAyah));
    url.searchParams.set("edition", editionId);
    url.searchParams.delete("ayah");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    window.localStorage.setItem("athar-memorize-range", `${surahNumber}:${fromAyah}:${toAyah}`);
  }, [surahNumber, fromAyah, toAyah, editionId]);

  const retry = useCallback(() => {
    setCatalogError("");
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  }, [surahNumber]);

  const selectSurah = (nextSurah: number) => {
    setSurahNumber(nextSurah);
    setFromAyah(1);
    setToAyah(1);
    updateActiveAyah(1);
  };

  const selectFrom = (nextFrom: number) => {
    const nextTo = Math.max(nextFrom, toAyah);
    setFromAyah(nextFrom);
    setToAyah(nextTo);
    updateActiveAyah(nextFrom);
  };

  const selectTo = (nextTo: number) => {
    setToAyah(Math.max(fromAyah, nextTo));
    if (activeAyah > nextTo) updateActiveAyah(fromAyah);
  };

  return (
    <section className="grid gap-4 sm:gap-[18px]" aria-label="مساحة تثبيت الحفظ">
      <Surface
        variant="toolbar"
        className="grid grid-cols-2 items-end gap-2 rounded-athar-md p-3 sm:grid-cols-4 md:sticky md:top-[calc(var(--bar-height)+.5rem)] md:z-20 lg:grid-cols-[minmax(150px,1.4fr)_repeat(2,minmax(92px,.55fr))_minmax(160px,1fr)_auto] lg:gap-3 lg:p-3.5"
      >
        <Field label="السورة" className="col-span-2 sm:col-span-2 lg:col-span-1">
          <SelectControl value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => (
              <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
            ))}
          </SelectControl>
        </Field>
        <Field label="من آية">
          <SelectControl value={fromAyah} onChange={(event) => selectFrom(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </SelectControl>
        </Field>
        <Field label="إلى آية">
          <SelectControl value={toAyah} onChange={(event) => selectTo(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.filter((number) => number >= fromAyah).map((number) => (
              <option key={number} value={number}>{toArabicDigits(number)}</option>
            ))}
          </SelectControl>
        </Field>
        <Field label="طبعة المصحف" className="col-span-2 sm:col-span-3 lg:col-span-1">
          <SelectControl value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
            {Object.values(MUSHAF_EDITIONS).map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </SelectControl>
        </Field>
        <Button
          className="col-span-2 sm:col-span-1"
          variant={concealed ? "primary" : "secondary"}
          aria-pressed={concealed}
          onClick={() => setConcealed((value) => !value)}
        >
          {concealed ? "أظهر نص النطاق" : "اختبر حفظي"}
        </Button>
      </Surface>

      {catalogError ? (
        <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
          {catalogError}
        </StatusState>
      ) : null}

      <Surface variant="subtle" className="grid gap-4 rounded-athar-md p-4 sm:grid-cols-[1fr_1fr_auto] sm:items-center" aria-label="ملخص نطاق التثبيت">
        <StatTile
          label="النطاق المختار"
          value={`${selectedSurah ? `سورة ${selectedSurah.name}` : "السورة"} · ${toArabicDigits(fromAyah)}–${toArabicDigits(toAyah)}`}
          className="bg-athar-surface"
        />
        <div className="grid gap-2">
          <StatTile
            label="موضع الجلسة"
            value={`الآية ${toArabicDigits(activeAyah)} · ${toArabicDigits(activeAyah - fromAyah + 1)} من ${toArabicDigits(rangeLength)}`}
            className="bg-athar-surface"
          />
          <ProgressBar value={activeAyah - fromAyah + 1} max={rangeLength} label="تقدّم نطاق التثبيت" />
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="quiet" onClick={() => updateActiveAyah(activeAyah - 1)} disabled={activeAyah <= fromAyah}>السابقة</Button>
          <Button size="sm" onClick={() => updateActiveAyah(activeAyah + 1)} disabled={activeAyah >= toAyah}>التالية</Button>
        </div>
      </Surface>

      <MemorizePlayer
        surahNumber={surahNumber}
        fromAyah={fromAyah}
        toAyah={toAyah}
        activeAyah={activeAyah}
        onActiveAyahChange={updateActiveAyah}
        onWordChange={setActiveAudioWord}
      />

      <Surface as="aside" className="grid w-full gap-3 overflow-hidden rounded-athar-md border-s-4 border-s-athar-gold p-4" aria-live="polite" aria-label="التفصيل الموضوعي">
        <header className="flex items-start justify-between gap-4">
          <div className="grid gap-0.5">
            <span className="text-[0.7rem] font-bold text-athar-gold">التفصيل الموضوعي</span>
            <h2 className="m-0 font-athar-display text-[clamp(1.35rem,3vw,1.9rem)] leading-tight text-athar-ink">
              {contextLoading ? "نراجع سياق الآية…" : visibleContext?.found ? visibleContext.title : "السياق الموضوعي"}
            </h2>
          </div>
          <span className="shrink-0 rounded-full bg-athar-line-soft px-3 py-1 text-[0.7rem] font-bold text-athar-ink-soft">
            الآية {toArabicDigits(activeAyah)}
          </span>
        </header>

        {contextLoading ? (
          <StatusState tone="loading">جارٍ تحميل التفصيل الموضوعي…</StatusState>
        ) : visibleContext?.found ? (
          <>
            <p className="m-0 text-sm leading-7 text-athar-ink-soft sm:text-base">{visibleContext.label}</p>
            <div className="grid gap-2">
              <div className="flex items-center justify-between gap-3 text-[0.7rem] text-athar-ink-faint">
                <span>تقدّمك داخل الموضوع</span>
                <span>{toArabicDigits(contextPosition)} / {toArabicDigits(contextLength)}</span>
              </div>
              <ProgressBar value={contextPosition} max={contextLength} label="موضع الآية داخل المقطع الموضوعي" />
            </div>
            <details className="group border-t border-athar-line-soft pt-3">
              <summary className="flex cursor-pointer list-none items-center gap-2 text-xs font-bold text-athar-ink-soft marker:content-none [&::-webkit-details-marker]:hidden">
                <span aria-hidden="true" className="text-athar-gold transition-transform group-open:rotate-90">‹</span>
                تفاصيل المقطع الموضوعي
              </summary>
              <div className="mt-3 grid gap-3">
                <div className="grid gap-2 sm:grid-cols-3">
                  <StatTile
                    label="المقطع الموضوعي"
                    value={contextRange ? `${toArabicDigits(contextRange[0])}–${toArabicDigits(contextRange[1])}` : `${toArabicDigits(visibleContext.run_length || 1)} آيات`}
                  />
                  <StatTile label="الآية الحالية" value={toArabicDigits(activeAyah)} />
                  <StatTile label="موضعها في المقطع" value={`${toArabicDigits(contextPosition)} من ${toArabicDigits(contextLength)}`} />
                </div>
                <p className="m-0 flex items-center gap-2 text-xs text-athar-ink-faint">
                  <span className="size-2.5 rounded-full bg-athar-gold/35" aria-hidden="true" />
                  التظليل الخفيف على صفحة المصحف يبيّن امتداد هذا الموضوع، والتظليل الأقوى يحدّد الآية الحالية.
                </p>
                {visibleContext.attribution ? <small className="text-xs text-athar-ink-faint">المصدر: {visibleContext.attribution}</small> : null}
              </div>
            </details>
          </>
        ) : (
          <StatusState className="justify-center">لا يتوفر تفصيل موضوعي موثّق لهذه الآية بعد.</StatusState>
        )}
      </Surface>

      <MushafRenderer
        view="page"
        editionId={editionId}
        ayah={null}
        page={visiblePage?.page || null}
        surahs={surahs}
        selectedSurah={selectedSurah}
        surahNumber={surahNumber}
        ayahNumber={activeAyah}
        isLoading={visiblePage === null}
        error={visiblePage?.error || ""}
        fontLoading={fontLoading}
        activeAudioWord={activeAudioWord}
        focusRange={[fromAyah, toAyah]}
        contextRange={contextRange}
        concealFocused={concealed}
        onRetry={retry}
      />

      <HandoffSurface action={<a href={legacyUrl(`/memorize?surah=${surahNumber}&from=${fromAyah}&to=${toAyah}`)}>افتح التسميع الصوتي</a>}>
        التكرار المقطعي والربط التراكمي انتقلا إلى هنا. التسميع الصوتي ما زال في النسخة السابقة أثناء إكمال النقل.
      </HandoffSurface>
    </section>
  );
}
