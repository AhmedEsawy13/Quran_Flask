"use client";

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { type Ayah, type MushafPage, type Surah, getJson } from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  isMushafEdition,
  isReaderLayout,
  isReaderView,
  juzLabel,
  juzNumberForPage,
  juzNumberFromAyah,
  juzStartPosition,
  spreadPageNumbers,
  toArabicDigits,
  type MushafEditionId,
  type ReaderLayout,
  type ReaderView,
} from "@/lib/mushaf";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { MushafStage } from "@/components/mushaf-stage";
import { ReaderAudio } from "@/components/reader-audio";
import { ReaderMushafGuide } from "@/components/reader-mushaf-guide";
import { ReaderStudy } from "@/components/reader-study";
import { Button, CheckControl, DrawerSurface, Field, SegmentedControl, SelectControl, StatusState, Surface } from "@/components/ui/primitives";
import { useEditionFont } from "@/lib/use-edition-font";
import { usePageTajweed } from "@/lib/use-page-tajweed";

type ContentResult = {
  requestKey: string;
  ayah: Ayah | null;
  page: MushafPage | null;
  error: string;
};

type SpreadResult = {
  requestKey: string;
  right: MushafPage | null;
  left: MushafPage | null;
  error: string;
};

type ReaderSupportPanel = "audio" | "study" | "guide";
type ReaderNavigator = "surah" | "juz" | "page";

function clampInteger(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, Math.trunc(value)));
}

function parsePositiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function firstVerseOnPage(page: MushafPage) {
  for (const line of page.lines) {
    for (const word of line.words) {
      const surah = Number(word.surah);
      const ayah = Number(word.ayah);
      if (Number.isInteger(surah) && Number.isInteger(ayah) && surah > 0 && ayah > 0) {
        return {surah, ayah};
      }
    }
  }
  const surah = Number(page.anchor_surah_number);
  const ayah = Number(page.anchor_ayah_number);
  return Number.isInteger(surah) && Number.isInteger(ayah) && surah > 0 && ayah > 0
    ? {surah, ayah}
    : null;
}

export function ReaderWorkspace() {
  const searchParams = useSearchParams();
  const restoreLastPosition = !searchParams.has("surah") && !searchParams.has("ayah");
  const restoreView = !searchParams.has("view");
  const restoreEdition = !searchParams.has("edition");
  const restoreLayout = !searchParams.has("layout");
  const restoreMargins = !searchParams.has("margins");
  const [positionReady, setPositionReady] = useState(!(restoreLastPosition || restoreView || restoreEdition || restoreLayout || restoreMargins));
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(() =>
    clampInteger(parsePositiveInteger(searchParams.get("surah"), 2), 1, 114),
  );
  const [ayahNumber, setAyahNumber] = useState(() =>
    parsePositiveInteger(searchParams.get("ayah"), 255),
  );
  const [view, setView] = useState<ReaderView>(() => {
    const value = searchParams.get("view");
    return isReaderView(value) ? value : "page";
  });
  const [editionId, setEditionId] = useState<MushafEditionId>(() => {
    const value = searchParams.get("edition");
    return isMushafEdition(value) ? value : "digital_khatt";
  });
  const [layout, setLayout] = useState<ReaderLayout>(() => {
    const value = searchParams.get("layout");
    return isReaderLayout(value) ? value : "dual";
  });
  const [dualAvailable, setDualAvailable] = useState(false);
  const [tajweedEnabled, setTajweedEnabled] = useState(false);
  const [catalogError, setCatalogError] = useState("");
  const [contentResult, setContentResult] = useState<ContentResult>({
    requestKey: "",
    ayah: null,
    page: null,
    error: "",
  });
  const [retryToken, setRetryToken] = useState(0);
  const [moving, setMoving] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [navigatorMode, setNavigatorMode] = useState<ReaderNavigator | null>(null);
  const [supportPanel, setSupportPanel] = useState<ReaderSupportPanel | null>(null);
  const [marginMode, setMarginMode] = useState(() => searchParams.get("margins") === "1");
  const [activeAudioWord, setActiveAudioWord] = useState<number | null>(null);
  const [reciterId, setReciterId] = useState("husary");
  const requestKey = `${view}:${editionId}:${surahNumber}:${ayahNumber}:${retryToken}`;
  const visibleResult = contentResult.requestKey === requestKey ? contentResult : null;
  const pageFontName = editionId === "shamarly" && visibleResult?.page?.glyph_mapping_mode === "shemrly-page-local"
    ? visibleResult.page.font_name
    : undefined;
  const fontLoading = useEditionFont(editionId, pageFontName);
  const isContentLoading = positionReady && visibleResult === null;
  const dualActive = view === "page" && layout === "dual" && dualAvailable && !marginMode;
  const visiblePageNumber = visibleResult?.page?.page_number || null;
  const edition = MUSHAF_EDITIONS[editionId];
  const [rightPageNumber, leftPageNumber] = visiblePageNumber && dualActive
    ? spreadPageNumbers(visiblePageNumber, edition.minPage, edition.maxPage)
    : [null, null];
  const spreadRequestKey = dualActive && visiblePageNumber
    ? `${editionId}:${rightPageNumber || 0}:${leftPageNumber || 0}:${retryToken}`
    : "";
  const [spreadResult, setSpreadResult] = useState<SpreadResult>({requestKey: "", right: null, left: null, error: ""});
  const visibleSpread = spreadResult.requestKey === spreadRequestKey ? spreadResult : null;
  const rightPage = dualActive
    ? (visibleResult?.page?.page_number === rightPageNumber ? visibleResult.page : visibleSpread?.right || null)
    : null;
  const leftPage = dualActive
    ? (visibleResult?.page?.page_number === leftPageNumber ? visibleResult.page : visibleSpread?.left || null)
    : null;
  const rightFontLoading = useEditionFont(
    editionId,
    editionId === "shamarly" && rightPage?.glyph_mapping_mode === "shemrly-page-local" ? rightPage.font_name : undefined,
  );
  const leftFontLoading = useEditionFont(
    editionId,
    editionId === "shamarly" && leftPage?.glyph_mapping_mode === "shemrly-page-local" ? leftPage.font_name : undefined,
  );
  const tajweedAvailable = view === "page" && editionId !== "shamarly";
  const tajweedOn = tajweedEnabled && tajweedAvailable;
  const tajweedPages = dualActive ? [rightPage, leftPage] : [visibleResult?.page || null];
  const {segmentsByWord: tajweedSegmentsByWord, loading: tajweedLoading} = usePageTajweed(tajweedPages, tajweedOn);

  useEffect(() => {
    if (!restoreLastPosition && !restoreView && !restoreEdition && !restoreLayout && !restoreMargins) return;
    const frame = window.requestAnimationFrame(() => {
      const savedPosition = window.localStorage.getItem("athar-reader-position");
      if (restoreLastPosition && savedPosition) {
        const [savedSurah, savedAyah] = savedPosition.split(":").map(Number);
        if (
          Number.isInteger(savedSurah) && Number.isInteger(savedAyah) &&
          savedSurah >= 1 && savedSurah <= 114 && savedAyah >= 1
        ) {
          setSurahNumber(savedSurah);
          setAyahNumber(savedAyah);
        }
      }
      const savedPreferences = window.localStorage.getItem("athar-reader-preferences");
      if (savedPreferences) {
        const [savedView, savedEdition, savedLayout] = savedPreferences.split(":");
        if (restoreView && isReaderView(savedView)) setView(savedView);
        if (restoreEdition && isMushafEdition(savedEdition)) setEditionId(savedEdition);
        if (restoreLayout && isReaderLayout(savedLayout)) setLayout(savedLayout);
      }
      const savedLayout = window.localStorage.getItem("athar-reader-layout");
      if (restoreLayout && isReaderLayout(savedLayout)) setLayout(savedLayout);
      if (restoreMargins) setMarginMode(window.localStorage.getItem("athar-reader-margins") === "true");
      setTajweedEnabled(
        window.localStorage.getItem("athar-reader-tajweed") === "true" ||
        window.localStorage.getItem("quranApp_tajweedEnabled") === "true",
      );
      setPositionReady(true);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [restoreEdition, restoreLastPosition, restoreLayout, restoreMargins, restoreView]);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1100px)");
    const update = () => setDualAvailable(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
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

  const loadAyahNumbers = useCallback(async (surah: number, signal?: AbortSignal) => {
    const cached = ayahCache.current.get(surah);
    if (cached) return cached;
    const numbers = await getJson<number[]>(`/backend-api/surahs/${surah}/ayahs`, signal);
    ayahCache.current.set(surah, numbers);
    return numbers;
  }, []);

  useEffect(() => {
    if (!positionReady) return;
    const controller = new AbortController();
    loadAyahNumbers(surahNumber, controller.signal)
      .then((numbers) => {
        setAyahNumbers(numbers);
        setCatalogError("");
        setAyahNumber((current) => {
          if (!numbers.length || numbers.includes(current)) return current;
          return current > numbers.length ? numbers[numbers.length - 1] : numbers[0];
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAyahNumbers([]);
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تحميل آيات السورة.");
      });
    return () => controller.abort();
  }, [surahNumber, positionReady, retryToken, loadAyahNumbers]);

  useEffect(() => {
    if (!positionReady) return;
    const controller = new AbortController();
    const edition = MUSHAF_EDITIONS[editionId];
    const usesExplicitMarks = editionId === "azhar_amiri" || editionId === "shamarly";
    const path = view === "page"
      ? `/backend-api/${edition.apiBase}/page-by-ayah/${surahNumber}/${ayahNumber}${usesExplicitMarks ? `?mushaf_version=${encodeURIComponent(edition.waqfSource)}` : ""}`
      : `/backend-api/surahs/${surahNumber}/ayahs/${ayahNumber}?source=qpc_hafs`;
    getJson<Ayah | MushafPage>(path, controller.signal)
      .then((data) => {
        setContentResult({
          requestKey,
          ayah: view === "verse" ? data as Ayah : null,
          page: view === "page" ? data as MushafPage : null,
          error: "",
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setContentResult({
          requestKey,
          ayah: null,
          page: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل المصحف.",
        });
      });
    return () => controller.abort();
  }, [positionReady, view, editionId, surahNumber, ayahNumber, retryToken, requestKey]);

  useEffect(() => {
    if (!dualActive || !visibleResult?.page || !spreadRequestKey) return;
    const controller = new AbortController();
    const usesExplicitMarks = editionId === "azhar_amiri" || editionId === "shamarly";
    const query = usesExplicitMarks
      ? `?mushaf_version=${encodeURIComponent(edition.waqfSource)}`
      : "";
    const loadPage = (pageNumber: number | null) => {
      if (!pageNumber) return Promise.resolve(null);
      if (visibleResult.page?.page_number === pageNumber) return Promise.resolve(visibleResult.page);
      return getJson<MushafPage>(
        `/backend-api/${edition.apiBase}/page/${pageNumber}${query}`,
        controller.signal,
      );
    };
    Promise.all([loadPage(rightPageNumber), loadPage(leftPageNumber)])
      .then(([right, left]) => setSpreadResult({requestKey: spreadRequestKey, right, left, error: ""}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setSpreadResult({
          requestKey: spreadRequestKey,
          right: null,
          left: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل صفحتي المصحف.",
        });
      });
    return () => controller.abort();
  }, [dualActive, edition, editionId, leftPageNumber, rightPageNumber, spreadRequestKey, visibleResult?.page]);

  useEffect(() => {
    if (!positionReady) return;
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("ayah", String(ayahNumber));
    url.searchParams.set("view", view);
    url.searchParams.set("edition", editionId);
    url.searchParams.set("layout", layout);
    if (marginMode) url.searchParams.set("margins", "1");
    else url.searchParams.delete("margins");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    window.localStorage.setItem("athar-reader-position", `${surahNumber}:${ayahNumber}`);
    window.localStorage.setItem("athar-reader-preferences", `${view}:${editionId}:${layout}`);
    window.localStorage.setItem("athar-reader-layout", layout);
    window.localStorage.setItem("athar-reader-margins", String(marginMode));
    window.localStorage.setItem("athar-reader-tajweed", String(tajweedEnabled));
  }, [positionReady, surahNumber, ayahNumber, view, editionId, layout, marginMode, tajweedEnabled]);

  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const currentJuz = visiblePageNumber
    ? juzNumberForPage(visiblePageNumber)
    : juzNumberFromAyah(surahNumber, ayahNumber);
  const pageNumbers = useMemo(
    () => Array.from({length: edition.maxPage - edition.minPage + 1}, (_, index) => edition.minPage + index),
    [edition.maxPage, edition.minPage],
  );
  const currentIndex = ayahNumbers.indexOf(ayahNumber);
  const atFirstAyah = surahNumber === 1 && ayahNumber === 1;
  const atLastAyah = surahNumber === 114 && currentIndex === ayahNumbers.length - 1;

  const retry = useCallback(() => {
    setCatalogError("");
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  }, [surahNumber]);

  const navigateToVerse = useCallback((surah: number, ayah: number) => {
    setCatalogError("");
    setSurahNumber(clampInteger(surah, 1, 114));
    setAyahNumber(Math.max(1, Math.trunc(ayah)));
  }, []);

  const jumpToPage = useCallback(async (targetPage: number) => {
    const safePage = clampInteger(targetPage, edition.minPage, edition.maxPage);
    setMoving(true);
    try {
      const usesExplicitMarks = editionId === "azhar_amiri" || editionId === "shamarly";
      const query = usesExplicitMarks
        ? `?mushaf_version=${encodeURIComponent(edition.waqfSource)}`
        : "";
      const target = await getJson<MushafPage>(
        `/backend-api/${edition.apiBase}/page/${safePage}${query}`,
      );
      const position = firstVerseOnPage(target);
      if (!position) throw new Error("لم يُعثر على أول آية في الصفحة.");
      navigateToVerse(position.surah, position.ayah);
      setNavigatorMode(null);
    } catch (reason: unknown) {
      setCatalogError(reason instanceof Error ? reason.message : "تعذّر الانتقال إلى الصفحة.");
    } finally {
      setMoving(false);
    }
  }, [edition.apiBase, edition.maxPage, edition.minPage, edition.waqfSource, editionId, navigateToVerse]);

  const jumpToJuz = (juz: number) => {
    const position = juzStartPosition(juz);
    navigateToVerse(position.surah, position.ayah);
    setNavigatorMode(null);
  };

  const jumpToSurah = (surah: number) => {
    navigateToVerse(surah, 1);
    setNavigatorMode(null);
  };

  const move = useCallback(async (direction: -1 | 1) => {
    if (moving) return;
    setMoving(true);
    try {
      if (direction > 0) {
        if (currentIndex >= 0 && currentIndex < ayahNumbers.length - 1) {
          setAyahNumber(ayahNumbers[currentIndex + 1]);
        } else if (surahNumber < 114) {
          setSurahNumber(surahNumber + 1);
          setAyahNumber(1);
        }
      } else if (currentIndex > 0) {
        setAyahNumber(ayahNumbers[currentIndex - 1]);
      } else if (surahNumber > 1) {
        const previousSurah = surahNumber - 1;
        const previousNumbers = await loadAyahNumbers(previousSurah);
        setSurahNumber(previousSurah);
        setAyahNumber(previousNumbers.at(-1) || 1);
      }
    } catch (reason: unknown) {
      setCatalogError(reason instanceof Error ? reason.message : "تعذّر الانتقال بين الآيات.");
    } finally {
      setMoving(false);
    }
  }, [moving, currentIndex, ayahNumbers, surahNumber, loadAyahNumbers]);
  const advanceAfterAudio = useCallback(() => move(1), [move]);

  const spreadNumbers = [rightPageNumber, leftPageNumber].filter((page): page is number => page !== null);
  const atFirstPage = visiblePageNumber !== null && (
    dualActive ? (spreadNumbers[0] || visiblePageNumber) <= edition.minPage : visiblePageNumber <= edition.minPage
  );
  const atLastPage = visiblePageNumber !== null && (
    dualActive ? (spreadNumbers.at(-1) || visiblePageNumber) >= edition.maxPage : visiblePageNumber >= edition.maxPage
  );

  const movePage = async (direction: -1 | 1) => {
    const pageNumber = visibleResult?.page?.page_number;
    if (moving || !pageNumber) return;
    const selectedEdition = MUSHAF_EDITIONS[editionId];
    const pairStart = dualActive
      ? (rightPageNumber ?? ((leftPageNumber ?? pageNumber) - 1))
      : pageNumber;
    const rawTargetPage = pairStart + direction * (dualActive ? 2 : 1);
    const targetPage = Math.max(selectedEdition.minPage, Math.min(selectedEdition.maxPage, rawTargetPage));
    if (targetPage < selectedEdition.minPage || targetPage > selectedEdition.maxPage) return;
    setMoving(true);
    try {
      const usesExplicitMarks = editionId === "azhar_amiri" || editionId === "shamarly";
      const query = usesExplicitMarks
        ? `?mushaf_version=${encodeURIComponent(selectedEdition.waqfSource)}`
        : "";
      const target = await getJson<MushafPage>(
        `/backend-api/${selectedEdition.apiBase}/page/${targetPage}${query}`,
      );
      const position = firstVerseOnPage(target);
      if (!position) throw new Error("لم يُعثر على أول آية في الصفحة.");
      navigateToVerse(position.surah, position.ayah);
    } catch (reason: unknown) {
      setCatalogError(reason instanceof Error ? reason.message : "تعذّر الانتقال بين الصفحات.");
    } finally {
      setMoving(false);
    }
  };

  const moveReading = (direction: -1 | 1) => {
    if (view === "page") return movePage(direction);
    return move(direction);
  };

  const previousDisabled = !ayahNumbers.length || (view === "page" ? !visiblePageNumber || atFirstPage : atFirstAyah);
  const nextDisabled = !ayahNumbers.length || (view === "page" ? !visiblePageNumber || atLastPage : atLastAyah);
  const positionLabel = view === "page" && visiblePageNumber
    ? `${dualActive && spreadNumbers.length > 1
      ? `صفحتا ${toArabicDigits(spreadNumbers[0])}–${toArabicDigits(spreadNumbers.at(-1) || spreadNumbers[0])}`
      : `صفحة ${toArabicDigits(visiblePageNumber)}`} · ${selectedSurah?.name || `سورة ${toArabicDigits(surahNumber)}`}`
    : `${selectedSurah?.name || `سورة ${toArabicDigits(surahNumber)}`} · آية ${toArabicDigits(ayahNumber)}`;
  const moveReadingEvent = useEffectEvent((direction: -1 | 1) => {
    void moveReading(direction);
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
        target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target?.tagName || "")
      ) return;
      if (event.key === "ArrowLeft" && !nextDisabled) {
        event.preventDefault();
        moveReadingEvent(1);
      } else if (event.key === "ArrowRight" && !previousDisabled) {
        event.preventDefault();
        moveReadingEvent(-1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [nextDisabled, previousDisabled]);

  const openSupportAfterSettings = (panel: ReaderSupportPanel) => {
    setSettingsOpen(false);
    window.requestAnimationFrame(() => setSupportPanel(panel));
  };

  const supportTitle = supportPanel === "audio"
    ? "الاستماع والتكرار"
    : supportPanel === "study"
      ? "هوامش الفهم"
      : "مفتاح الصفحة";

  return (
    <section className="reader-workspace relative grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-2" aria-label="قارئ المصحف">
      <Surface variant="toolbar" className="reader-reading-bar" aria-label="أدوات القراءة السريعة">
        <div className="flex min-h-10 items-center gap-1.5 md:hidden">
          <Button
            size="icon"
            variant="quiet"
            className="size-9 shrink-0 text-base"
            aria-label="إعدادات القراءة"
            aria-expanded={settingsOpen}
            aria-controls={settingsOpen ? "reader-settings-drawer" : undefined}
            onClick={() => setSettingsOpen(true)}
          >
            ⚙
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="size-9 shrink-0 text-xs"
            aria-label="فتح مشغّل التلاوة"
            onClick={() => setSupportPanel("audio")}
          >
            ▶
          </Button>
          <button
            type="button"
            className="min-w-0 flex-1 cursor-pointer rounded-lg border-0 bg-transparent px-1 text-center focus-visible:outline-2 focus-visible:outline-athar-accent"
            aria-label="فتح فهرس المصحف"
            onClick={() => setNavigatorMode("surah")}
          >
            <strong className="block truncate text-sm text-athar-ink">{positionLabel}</strong>
            <span className="block truncate text-[0.65rem] text-athar-ink-faint">{edition.shortLabel}</span>
          </button>
          <SegmentedControl
            label="طريقة العرض"
            value={view}
            options={[{value: "page", label: "صفحة"}, {value: "verse", label: "آية"}]}
            onChange={setView}
            className="w-[116px] shrink-0"
          />
          <Button
            size="icon"
            variant="ghost"
            className="size-9 shrink-0 text-xs"
            aria-label="فتح هوامش فهم الآية"
            onClick={() => setSupportPanel("study")}
          >
            شرح
          </Button>
        </div>

        <div className="hidden items-end gap-2 md:grid md:grid-cols-[auto_minmax(150px,1fr)_minmax(80px,.38fr)_minmax(170px,.9fr)_auto] lg:gap-2.5">
          <SegmentedControl
            label="طريقة العرض"
            value={view}
            options={[{value: "page", label: "صفحة"}, {value: "verse", label: "آية"}]}
            onChange={setView}
          />
          <Field label="السورة">
            <SelectControl
              value={surahNumber}
              onChange={(event) => {
                setCatalogError("");
                setSurahNumber(Number(event.target.value));
                setAyahNumber(1);
              }}
              disabled={!surahs.length}
            >
              {!surahs.length ? <option>جارٍ التحميل…</option> : null}
              {surahs.map((surah) => (
                <option key={surah.number} value={surah.number}>
                  {toArabicDigits(surah.number)}. {surah.name}
                </option>
              ))}
            </SelectControl>
          </Field>
          <Field label="الآية">
            <SelectControl
              value={ayahNumber}
              onChange={(event) => setAyahNumber(Number(event.target.value))}
              disabled={!ayahNumbers.length}
            >
              {!ayahNumbers.length ? <option>{toArabicDigits(ayahNumber)}</option> : null}
              {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
            </SelectControl>
          </Field>
          <Field label="رسم الصفحة">
            <SelectControl value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
              {Object.values(MUSHAF_EDITIONS).map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </SelectControl>
          </Field>
          <div className="flex items-center gap-1.5 self-end border-s border-athar-line-soft ps-2">
            <Button
              size="sm"
              variant="ghost"
              className="px-2.5"
              onClick={() => setSupportPanel("audio")}
            >
              ▶ استماع
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="px-2.5"
              onClick={() => setSupportPanel("study")}
            >
              فهم الآية
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="hidden px-2.5 xl:inline-flex"
              onClick={() => setSupportPanel("guide")}
            >
              مفتاح الصفحة
            </Button>
            <Button
              size="sm"
              variant={marginMode ? "quiet" : "ghost"}
              className="hidden px-2.5 xl:inline-flex"
              aria-pressed={marginMode}
              disabled={view !== "page"}
              onClick={() => setMarginMode((current) => !current)}
            >
              الهوامش
            </Button>
            <Button
              size="sm"
              variant={layout === "dual" ? "quiet" : "ghost"}
              className="hidden px-2.5 xl:inline-flex"
              aria-pressed={layout === "dual"}
              disabled={view !== "page" || marginMode}
              onClick={() => setLayout((current) => current === "dual" ? "single" : "dual")}
            >
              {layout === "dual" ? "صفحتان" : "صفحة واحدة"}
            </Button>
            <Button
              size="sm"
              variant={tajweedOn ? "quiet" : "ghost"}
              className="hidden px-2.5 xl:inline-flex"
              aria-pressed={tajweedOn}
              disabled={!tajweedAvailable}
              title={editionId === "shamarly" ? "التلوين الحرفي غير متاح مع خط الشمرلي" : "تلوين أحكام التجويد حرفيًا"}
              onClick={() => setTajweedEnabled((current) => !current)}
            >
              {tajweedLoading ? "يُحمّل…" : "تلوين التجويد"}
            </Button>
            <Button
              size="icon"
              variant="quiet"
              className="size-9"
              aria-label="المزيد من إعدادات القراءة"
              aria-expanded={settingsOpen}
              aria-controls={settingsOpen ? "reader-settings-drawer" : undefined}
              onClick={() => setSettingsOpen(true)}
            >
              ⚙
            </Button>
          </div>
        </div>
      </Surface>

      <DrawerSurface
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        eyebrow={positionLabel}
        title="إعدادات القراءة"
        id="reader-settings-drawer"
        overlay
      >
        <div className="mb-4 grid grid-cols-3 gap-2 border-b border-athar-line-soft pb-4" aria-label="الوصول السريع">
          <Button size="sm" variant="quiet" onClick={() => openSupportAfterSettings("audio")}>▶ استماع</Button>
          <Button size="sm" variant="quiet" onClick={() => openSupportAfterSettings("study")}>فهم الآية</Button>
          <Button size="sm" variant="quiet" onClick={() => openSupportAfterSettings("guide")}>مفتاح الصفحة</Button>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-1 text-[0.7rem] text-athar-ink-faint sm:col-span-2">
            <span>طريقة العرض</span>
            <SegmentedControl
              label="طريقة العرض"
              value={view}
              options={[{value: "page", label: "صفحة كاملة"}, {value: "verse", label: "آية مركّزة"}]}
              onChange={setView}
            />
          </div>
          <Field label="السورة">
            <SelectControl
              value={surahNumber}
              onChange={(event) => {
                setCatalogError("");
                setSurahNumber(Number(event.target.value));
                setAyahNumber(1);
              }}
              disabled={!surahs.length}
            >
              {!surahs.length ? <option>جارٍ التحميل…</option> : null}
              {surahs.map((surah) => <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>)}
            </SelectControl>
          </Field>
          <Field label="الآية">
            <SelectControl value={ayahNumber} onChange={(event) => setAyahNumber(Number(event.target.value))} disabled={!ayahNumbers.length}>
              {!ayahNumbers.length ? <option>{toArabicDigits(ayahNumber)}</option> : null}
              {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
            </SelectControl>
          </Field>
          <Field label="رسم الصفحة" className="sm:col-span-2">
            <SelectControl value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
              {Object.values(MUSHAF_EDITIONS).map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </SelectControl>
          </Field>
          <CheckControl
            label="صفحتان متقابلتان على الشاشة الواسعة"
            checked={layout === "dual"}
            disabled={view !== "page" || marginMode}
            onChange={(event) => setLayout(event.target.checked ? "dual" : "single")}
          />
          <CheckControl
            label="هوامش كصفحة تفسير مطبوعة"
            checked={marginMode}
            disabled={view !== "page"}
            onChange={(event) => setMarginMode(event.target.checked)}
          />
          <CheckControl
            label={editionId === "shamarly" ? "التجويد غير متاح مع الشمرلي" : "تلوين أحكام التجويد"}
            checked={tajweedOn}
            disabled={!tajweedAvailable}
            onChange={(event) => setTajweedEnabled(event.target.checked)}
          />
        </div>
      </DrawerSurface>

      <DrawerSurface
        open={navigatorMode !== null}
        onClose={() => setNavigatorMode(null)}
        eyebrow={positionLabel}
        title="فهرس المصحف"
        id="reader-navigator-drawer"
        overlay
      >
        <div className="grid gap-4">
          <SegmentedControl
            label="نوع الانتقال"
            value={navigatorMode || "surah"}
            options={[
              {value: "surah", label: "السورة"},
              {value: "juz", label: "الجزء"},
              {value: "page", label: "الصفحة"},
            ]}
            onChange={setNavigatorMode}
          />
          {navigatorMode === "surah" ? (
            <Field label="اختر السورة" hint="ينقلك إلى أول آية في السورة">
              <SelectControl value={surahNumber} onChange={(event) => jumpToSurah(Number(event.target.value))}>
                {surahs.map((surah) => (
                  <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
                ))}
              </SelectControl>
            </Field>
          ) : null}
          {navigatorMode === "juz" ? (
            <Field label="اختر الجزء" hint="ينقلك إلى بداية الجزء">
              <SelectControl value={currentJuz} onChange={(event) => jumpToJuz(Number(event.target.value))}>
                {Array.from({length: 30}, (_, index) => index + 1).map((juz) => (
                  <option key={juz} value={juz}>{juzLabel(juz)}</option>
                ))}
              </SelectControl>
            </Field>
          ) : null}
          {navigatorMode === "page" ? (
            <Field label="اختر الصفحة" hint={`${edition.label} · ${toArabicDigits(edition.minPage)}–${toArabicDigits(edition.maxPage)}`}>
              <SelectControl
                value={visiblePageNumber || edition.minPage}
                disabled={moving}
                onChange={(event) => void jumpToPage(Number(event.target.value))}
              >
                {pageNumbers.map((page) => <option key={page} value={page}>صفحة {toArabicDigits(page)}</option>)}
              </SelectControl>
            </Field>
          ) : null}
          <p className="m-0 text-xs leading-6 text-athar-ink-faint">
            يمكنك فتح هذا الفهرس مباشرةً بالضغط على اسم السورة أو الجزء أو رقم الصفحة داخل المصحف.
          </p>
        </div>
      </DrawerSurface>

      {catalogError ? (
        <StatusState tone="error" className="absolute inset-x-3 top-[4.5rem] z-40" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
          {catalogError}
        </StatusState>
      ) : null}

      <div className={`reader-reading-desk${marginMode && view === "page" ? " has-margins" : ""}`}>
        <aside className="reader-page-margin is-index" aria-label="فهرس الصفحة">
          <span className="reader-margin-kicker">فهرس الصفحة</span>
          <button type="button" className="reader-margin-action" onClick={() => setNavigatorMode("surah")}>
            <span>السورة</span><strong>{selectedSurah?.name || toArabicDigits(surahNumber)}</strong>
          </button>
          <button type="button" className="reader-margin-action" onClick={() => setNavigatorMode("juz")}>
            <span>الجزء</span><strong>{juzLabel(currentJuz)}</strong>
          </button>
          <button type="button" className="reader-margin-action" onClick={() => setNavigatorMode("page")}>
            <span>الصفحة</span><strong>{toArabicDigits(visiblePageNumber || edition.minPage)}</strong>
          </button>
          <p>اضغط عناوين الصفحة المطبوعة أو هذا الفهرس للانتقال دون مغادرة المصحف.</p>
        </aside>

        <MushafStage
          fill
          view={view}
          editionId={editionId}
          pageCount={dualActive ? 2 : 1}
          positionLabel={positionLabel}
          previousLabel={view === "page" ? "الصفحة السابقة" : "الآية السابقة"}
          nextLabel={view === "page" ? "الصفحة التالية" : "الآية التالية"}
          previousDisabled={previousDisabled}
          nextDisabled={nextDisabled}
          moving={moving}
          onPrevious={() => void moveReading(-1)}
          onNext={() => void moveReading(1)}
        >
          {dualActive ? (
            <div className="reader-mushaf-spread" aria-label="صفحتان متقابلتان">
              {rightPageNumber ? (
                <MushafRenderer
                  view="page"
                  editionId={editionId}
                  ayah={null}
                  page={rightPage}
                  surahs={surahs}
                  selectedSurah={selectedSurah}
                  surahNumber={surahNumber}
                  ayahNumber={ayahNumber}
                  isLoading={!rightPage && !visibleSpread?.error}
                  error={visibleSpread?.error || ""}
                  fontLoading={rightPage === visibleResult?.page ? fontLoading : rightFontLoading}
                  activeAudioWord={activeAudioWord}
                  tajweedEnabled={tajweedOn}
                  tajweedLoading={tajweedLoading}
                  tajweedSegmentsByWord={tajweedSegmentsByWord}
                  dualLayout
                  onSurahNavigate={() => setNavigatorMode("surah")}
                  onJuzNavigate={() => setNavigatorMode("juz")}
                  onPageNavigate={() => setNavigatorMode("page")}
                  onRetry={retry}
                />
              ) : <div className="reader-facing-blank" aria-hidden="true" />}
              {leftPageNumber ? (
                <MushafRenderer
                  view="page"
                  editionId={editionId}
                  ayah={null}
                  page={leftPage}
                  surahs={surahs}
                  selectedSurah={selectedSurah}
                  surahNumber={surahNumber}
                  ayahNumber={ayahNumber}
                  isLoading={!leftPage && !visibleSpread?.error}
                  error={visibleSpread?.error || ""}
                  fontLoading={leftPage === visibleResult?.page ? fontLoading : leftFontLoading}
                  activeAudioWord={activeAudioWord}
                  tajweedEnabled={tajweedOn}
                  tajweedLoading={tajweedLoading}
                  tajweedSegmentsByWord={tajweedSegmentsByWord}
                  dualLayout
                  onSurahNavigate={() => setNavigatorMode("surah")}
                  onJuzNavigate={() => setNavigatorMode("juz")}
                  onPageNavigate={() => setNavigatorMode("page")}
                  onRetry={retry}
                />
              ) : <div className="reader-facing-blank" aria-hidden="true" />}
            </div>
          ) : (
            <MushafRenderer
              view={view}
              editionId={editionId}
              ayah={visibleResult?.ayah || null}
              page={visibleResult?.page || null}
              surahs={surahs}
              selectedSurah={selectedSurah}
              surahNumber={surahNumber}
              ayahNumber={ayahNumber}
              isLoading={!positionReady || isContentLoading}
              error={visibleResult?.error || ""}
              fontLoading={fontLoading}
              activeAudioWord={activeAudioWord}
              tajweedEnabled={tajweedOn}
              tajweedLoading={tajweedLoading}
              tajweedSegmentsByWord={tajweedSegmentsByWord}
              onSurahNavigate={() => setNavigatorMode("surah")}
              onJuzNavigate={() => setNavigatorMode("juz")}
              onPageNavigate={() => setNavigatorMode("page")}
              onRetry={retry}
            />
          )}
        </MushafStage>

        <aside className="reader-page-margin is-tools" aria-label="هوامش الصفحة">
          <span className="reader-margin-kicker">الهوامش</span>
          <h2>اقرأ، ثم افتح ما تحتاجه فقط.</h2>
          <button type="button" className="reader-margin-action" onClick={() => setSupportPanel("study")}>
            <span>الفهم</span><strong>التفسير والمعاني</strong>
          </button>
          <button type="button" className="reader-margin-action" onClick={() => setSupportPanel("audio")}>
            <span>السماع</span><strong>التلاوة والتكرار</strong>
          </button>
          <button type="button" className="reader-margin-action" onClick={() => setSupportPanel("guide")}>
            <span>القراءة</span><strong>الوقف ودليل التلاوة</strong>
          </button>
          <p>تفتح الأدوات في هامش مستقل، لذلك تبقى صفحة القرآن كاملة في موضعها.</p>
        </aside>
      </div>

      <DrawerSurface
        open={supportPanel !== null}
        onClose={() => setSupportPanel(null)}
        eyebrow={`${selectedSurah?.name || "السورة"} · ${toArabicDigits(ayahNumber)}`}
        title={supportTitle}
        id="reader-support-drawer"
        overlay
      >
        {supportPanel === "audio" ? (
          <ReaderAudio
            surahNumber={surahNumber}
            ayahNumber={ayahNumber}
            onAdvance={advanceAfterAudio}
            atLastAyah={atLastAyah}
            onWordChange={setActiveAudioWord}
            onReciterChange={setReciterId}
          />
        ) : null}
        {supportPanel === "study" ? (
          <ReaderStudy
            surahNumber={surahNumber}
            ayahNumber={ayahNumber}
            initialAyah={visibleResult?.ayah || null}
            surahs={surahs}
            onNavigate={navigateToVerse}
          />
        ) : null}
        {supportPanel === "guide" ? (
          <ReaderMushafGuide
            surahNumber={surahNumber}
            ayahNumber={ayahNumber}
            editionId={editionId}
            reciterId={reciterId}
          />
        ) : null}
      </DrawerSurface>
    </section>
  );
}
