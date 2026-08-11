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
  const fontLoading = useEditionFont(editionId);
  const edition = MUSHAF_EDITIONS[editionId];
  const pageKey = `${editionId}:${surahNumber}:${activeAyah}:${retryToken}`;
  const contextKey = `${surahNumber}:${activeAyah}:${retryToken}`;
  const visiblePage = pageResult.key === pageKey ? pageResult : null;
  const visibleContext = contextResult.key === contextKey ? contextResult.data : null;
  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const rangeLength = Math.max(1, toAyah - fromAyah + 1);
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
    getJson<MushafPage>(
      `/backend-api/${edition.apiBase}/page-by-ayah/${surahNumber}/${activeAyah}`,
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
  }, [edition.apiBase, editionId, surahNumber, activeAyah, retryToken, pageKey]);

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
    <section className="memorize-workspace" aria-label="مساحة تثبيت الحفظ">
      <div className="memorize-toolbar">
        <label><span>السورة</span>
          <select value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => (
              <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
            ))}
          </select>
        </label>
        <label><span>من آية</span>
          <select value={fromAyah} onChange={(event) => selectFrom(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </select>
        </label>
        <label><span>إلى آية</span>
          <select value={toAyah} onChange={(event) => selectTo(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.filter((number) => number >= fromAyah).map((number) => (
              <option key={number} value={number}>{toArabicDigits(number)}</option>
            ))}
          </select>
        </label>
        <label><span>طبعة المصحف</span>
          <select value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
            {Object.values(MUSHAF_EDITIONS).map((item) => (
              <option key={item.id} value={item.id}>{item.label}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={`memorize-hide${concealed ? " is-on" : ""}`}
          aria-pressed={concealed}
          onClick={() => setConcealed((value) => !value)}
        >
          {concealed ? "أظهر نص النطاق" : "اختبر حفظي"}
        </button>
      </div>

      {catalogError ? (
        <div className="reader-alert" role="alert">
          <span>{catalogError}</span>
          <button type="button" onClick={retry}>أعد المحاولة</button>
        </div>
      ) : null}

      <div className="memorize-session-strip" aria-label="ملخص نطاق التثبيت">
        <div>
          <span>النطاق المختار</span>
          <strong>
            {selectedSurah ? `سورة ${selectedSurah.name}` : "السورة"} · {toArabicDigits(fromAyah)}–{toArabicDigits(toAyah)}
          </strong>
        </div>
        <div>
          <span>موضع الجلسة</span>
          <strong>الآية {toArabicDigits(activeAyah)} · {toArabicDigits(activeAyah - fromAyah + 1)} من {toArabicDigits(rangeLength)}</strong>
        </div>
        <div className="reader-stepper">
          <button type="button" onClick={() => updateActiveAyah(activeAyah - 1)} disabled={activeAyah <= fromAyah}>السابقة</button>
          <button type="button" onClick={() => updateActiveAyah(activeAyah + 1)} disabled={activeAyah >= toAyah}>التالية</button>
        </div>
      </div>

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
        concealFocused={concealed}
        onRetry={retry}
      />

      <MemorizePlayer
        surahNumber={surahNumber}
        fromAyah={fromAyah}
        toAyah={toAyah}
        activeAyah={activeAyah}
        onActiveAyahChange={updateActiveAyah}
        onWordChange={setActiveAudioWord}
      />

      <aside className="memorize-context" aria-live="polite">
        <span className="reader-panel-kicker">التفصيل الموضوعي</span>
        {visibleContext?.found ? (
          <>
            <strong>{visibleContext.title}</strong>
            <p>{visibleContext.label}</p>
            <small>{visibleContext.attribution}</small>
          </>
        ) : (
          <p>لا يتوفر تفصيل موضوعي موثّق لهذه الآية بعد.</p>
        )}
      </aside>

      <div className="reader-handoff">
        <span>التكرار المقطعي والربط التراكمي انتقلا إلى هنا. التسميع الصوتي ما زال في النسخة السابقة أثناء إكمال النقل.</span>
        <a href={legacyUrl(`/memorize?surah=${surahNumber}&from=${fromAyah}&to=${toAyah}`)}>افتح التسميع الصوتي</a>
      </div>
    </section>
  );
}
