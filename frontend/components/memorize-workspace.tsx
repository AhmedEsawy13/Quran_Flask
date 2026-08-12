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
import { pillActionClassName } from "@/lib/ui";
import { useEditionFont } from "@/lib/use-edition-font";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { MushafStage } from "@/components/mushaf-stage";
import { MemorizePlayer } from "@/components/memorize-player";
import {
  ChromeField,
  ChromePill,
  ChromeSelect,
  ChromeStepper,
  ToolCard,
  ToolChrome,
  ToolStack,
} from "@/components/tool-chrome";
import {
  Button,
  ProgressBar,
  StatTile,
  StatusState,
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
    <div aria-label="مساحة تثبيت الحفظ">
      <ToolChrome
        label="اختيار نطاق التثبيت"
        pill={(
          <ChromePill role="status" aria-label="ملخص نطاق التثبيت">
            {selectedSurah ? `سورة ${selectedSurah.name}` : "السورة"} · {toArabicDigits(fromAyah)}–{toArabicDigits(toAyah)}
          </ChromePill>
        )}
        note="اختر نطاق الآيات، ثم شغّل التكرار على صفحة المصحف. اضغط آيةً للتنقّل داخل النطاق."
      >
        <ChromeField label="السورة">
          <ChromeSelect value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => (
              <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
            ))}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="من آية">
          <ChromeSelect value={fromAyah} onChange={(event) => selectFrom(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="إلى آية">
          <ChromeSelect value={toAyah} onChange={(event) => selectTo(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.filter((number) => number >= fromAyah).map((number) => (
              <option key={number} value={number}>{toArabicDigits(number)}</option>
            ))}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="طبعة المصحف">
          <ChromeSelect value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
            {Object.values(MUSHAF_EDITIONS).map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </ChromeSelect>
        </ChromeField>
        <Button
          size="sm"
          variant={concealed ? "primary" : "secondary"}
          className="self-end"
          aria-pressed={concealed}
          onClick={() => setConcealed((value) => !value)}
        >
          {concealed ? "أظهر نص النطاق" : "اختبر حفظي"}
        </Button>
        <ChromeStepper
          previousLabel="الآية السابقة في نطاق التثبيت"
          nextLabel="الآية التالية في نطاق التثبيت"
          previousDisabled={activeAyah <= fromAyah}
          nextDisabled={activeAyah >= toAyah}
          onPrevious={() => updateActiveAyah(activeAyah - 1)}
          onNext={() => updateActiveAyah(activeAyah + 1)}
        />
      </ToolChrome>

      <ToolStack>
        {catalogError ? (
          <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
            {catalogError}
          </StatusState>
        ) : null}

        <MushafStage
        view="page"
        editionId={editionId}
        positionLabel={`${selectedSurah?.name || `سورة ${toArabicDigits(surahNumber)}`} · ${toArabicDigits(fromAyah)}–${toArabicDigits(toAyah)} · الآية ${toArabicDigits(activeAyah)}`}
        previousLabel="الآية السابقة في نطاق التثبيت"
        nextLabel="الآية التالية في نطاق التثبيت"
        previousDisabled={activeAyah <= fromAyah}
        nextDisabled={activeAyah >= toAyah}
        onPrevious={() => updateActiveAyah(activeAyah - 1)}
        onNext={() => updateActiveAyah(activeAyah + 1)}
      >
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
      </MushafStage>

      <MemorizePlayer
        surahNumber={surahNumber}
        fromAyah={fromAyah}
        toAyah={toAyah}
        activeAyah={activeAyah}
        onActiveAyahChange={updateActiveAyah}
        onWordChange={setActiveAudioWord}
      />

      <ToolCard as="aside" className="border-s-4 border-s-athar-gold" aria-live="polite" aria-label="التفصيل الموضوعي">
        <header className="mb-3 flex items-start justify-between gap-4">
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
            <div className="mt-3 grid gap-2">
              <div className="flex items-center justify-between gap-3 text-[0.7rem] text-athar-ink-faint">
                <span>تقدّمك داخل الموضوع</span>
                <span>{toArabicDigits(contextPosition)} / {toArabicDigits(contextLength)}</span>
              </div>
              <ProgressBar value={contextPosition} max={contextLength} label="موضع الآية داخل المقطع الموضوعي" />
            </div>
            <details className="group mt-3 border-t border-athar-line-soft pt-3">
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
      </ToolCard>

      <ToolCard aria-labelledby="mz-handoff-title">
        <div className="flex max-w-[42rem] flex-col gap-2">
          <h2 className="m-0 font-athar-display text-[1.1rem] font-bold text-athar-ink" id="mz-handoff-title">التسميع الصوتي</h2>
          <p className="m-0 text-[0.9rem] leading-relaxed text-athar-ink-soft">
            التكرار المقطعي والربط التراكمي هنا. التسميع الصوتي ما زال في النسخة السابقة أثناء إكمال النقل.
          </p>
          <a className={pillActionClassName("mt-1.5")} href={legacyUrl(`/memorize?surah=${surahNumber}&from=${fromAyah}&to=${toAyah}`)}>
            افتح التسميع الصوتي
          </a>
        </div>
      </ToolCard>
      </ToolStack>
    </div>
  );
}
