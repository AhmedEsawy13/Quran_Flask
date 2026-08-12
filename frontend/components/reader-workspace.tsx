"use client";

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { type Ayah, type MushafPage, type Surah, getJson } from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  isMushafEdition,
  isReaderLayout,
  isReaderView,
  toArabicDigits,
  type MushafEditionId,
  type ReaderLayout,
  type ReaderView,
} from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { MushafStage } from "@/components/mushaf-stage";
import { ReaderAudio } from "@/components/reader-audio";
import { ReaderMushafGuide } from "@/components/reader-mushaf-guide";
import { ReaderStudy } from "@/components/reader-study";
import { Button, CheckControl, DrawerSurface, Field, HandoffSurface, SegmentedControl, SelectControl, StatusState, Surface } from "@/components/ui/primitives";
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

// Printed RTL Mushaf spread: odd page on the right, following even page on the
// left. A missing cover-side at an edition boundary stays intentionally blank.
function spreadPageNumbers(page: number, minimum: number, maximum: number): [number | null, number | null] {
  const right = page % 2 === 1 ? page : page - 1;
  const left = right + 1;
  return [right >= minimum ? right : null, left <= maximum ? left : null];
}

export function ReaderWorkspace() {
  const searchParams = useSearchParams();
  const restoreLastPosition = !searchParams.has("surah") && !searchParams.has("ayah");
  const restoreView = !searchParams.has("view");
  const restoreEdition = !searchParams.has("edition");
  const restoreLayout = !searchParams.has("layout");
  const [positionReady, setPositionReady] = useState(!(restoreLastPosition || restoreView || restoreEdition || restoreLayout));
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
  const [activeAudioWord, setActiveAudioWord] = useState<number | null>(null);
  const [reciterId, setReciterId] = useState("husary");
  const requestKey = `${view}:${editionId}:${surahNumber}:${ayahNumber}:${retryToken}`;
  const visibleResult = contentResult.requestKey === requestKey ? contentResult : null;
  const pageFontName = editionId === "shamarly" && visibleResult?.page?.glyph_mapping_mode === "shemrly-page-local"
    ? visibleResult.page.font_name
    : undefined;
  const fontLoading = useEditionFont(editionId, pageFontName);
  const isContentLoading = positionReady && visibleResult === null;
  const dualActive = view === "page" && layout === "dual" && dualAvailable;
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
    if (!restoreLastPosition && !restoreView && !restoreEdition && !restoreLayout) return;
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
      setTajweedEnabled(
        window.localStorage.getItem("athar-reader-tajweed") === "true" ||
        window.localStorage.getItem("quranApp_tajweedEnabled") === "true",
      );
      setPositionReady(true);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [restoreEdition, restoreLastPosition, restoreLayout, restoreView]);

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
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    window.localStorage.setItem("athar-reader-position", `${surahNumber}:${ayahNumber}`);
    window.localStorage.setItem("athar-reader-preferences", `${view}:${editionId}:${layout}`);
    window.localStorage.setItem("athar-reader-layout", layout);
    window.localStorage.setItem("athar-reader-tajweed", String(tajweedEnabled));
  }, [positionReady, surahNumber, ayahNumber, view, editionId, layout, tajweedEnabled]);

  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
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

  return (
    <section className="reader-workspace grid gap-3.5 sm:gap-4" aria-label="قارئ المصحف">
      <Surface variant="toolbar" className="reader-reading-bar">
        <div className="flex min-h-12 items-center gap-2 md:hidden">
          <Button
            size="sm"
            variant="quiet"
            className="shrink-0 px-3"
            aria-expanded={settingsOpen}
            aria-controls={settingsOpen ? "reader-settings-drawer" : undefined}
            onClick={() => setSettingsOpen(true)}
          >
            إعدادات القراءة
          </Button>
          <div className="min-w-0 flex-1 text-center">
            <strong className="block truncate text-sm text-athar-ink">{positionLabel}</strong>
            <span className="block truncate text-[0.65rem] text-athar-ink-faint">{edition.shortLabel}</span>
          </div>
          <SegmentedControl
            label="طريقة العرض"
            value={view}
            options={[{value: "page", label: "صفحة"}, {value: "verse", label: "آية"}]}
            onChange={setView}
            className="w-[116px] shrink-0"
          />
        </div>

        <div className="hidden items-end gap-2 md:grid md:grid-cols-[auto_minmax(180px,1fr)_minmax(90px,.42fr)_minmax(185px,1fr)] lg:gap-3">
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
        </div>
        <div className="mt-2 hidden items-center justify-between gap-3 border-t border-athar-line-soft pt-2 md:flex">
          <span className="truncate text-xs text-athar-ink-faint">{positionLabel}</span>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={layout === "dual" ? "quiet" : "ghost"}
              aria-pressed={layout === "dual"}
              disabled={view !== "page"}
              onClick={() => setLayout((current) => current === "dual" ? "single" : "dual")}
            >
              {layout === "dual" ? "صفحتان متقابلتان" : "صفحة واحدة"}
            </Button>
            <Button
              size="sm"
              variant={tajweedOn ? "quiet" : "ghost"}
              aria-pressed={tajweedOn}
              disabled={!tajweedAvailable}
              title={editionId === "shamarly" ? "التلوين الحرفي غير متاح مع خط الشمرلي" : "تلوين أحكام التجويد حرفيًا"}
              onClick={() => setTajweedEnabled((current) => !current)}
            >
              {tajweedLoading ? "يُحمّل التجويد…" : "تلوين التجويد"}
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
      >
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
            disabled={view !== "page"}
            onChange={(event) => setLayout(event.target.checked ? "dual" : "single")}
          />
          <CheckControl
            label={editionId === "shamarly" ? "التجويد غير متاح مع الشمرلي" : "تلوين أحكام التجويد"}
            checked={tajweedOn}
            disabled={!tajweedAvailable}
            onChange={(event) => setTajweedEnabled(event.target.checked)}
          />
        </div>
      </DrawerSurface>

      <p className="reader-keyboard-hint">← {view === "page" ? "للصفحة التالية" : "للآية التالية"} · → للسابقة</p>

      {catalogError ? (
        <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
          {catalogError}
        </StatusState>
      ) : null}

      <MushafStage
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
            onRetry={retry}
          />
        )}
      </MushafStage>

      <ReaderAudio
        surahNumber={surahNumber}
        ayahNumber={ayahNumber}
        onAdvance={advanceAfterAudio}
        atLastAyah={atLastAyah}
        onWordChange={setActiveAudioWord}
        onReciterChange={setReciterId}
      />

      <ReaderStudy
        surahNumber={surahNumber}
        ayahNumber={ayahNumber}
        initialAyah={visibleResult?.ayah || null}
        surahs={surahs}
        onNavigate={navigateToVerse}
      />

      <ReaderMushafGuide
        surahNumber={surahNumber}
        ayahNumber={ayahNumber}
        editionId={editionId}
        reciterId={reciterId}
      />

      <HandoffSurface action={<a href={legacyUrl(`/read?surah=${surahNumber}&ayah=${ayahNumber}`)}>أدوات القراءة السابقة</a>}>
        تحتاج أداة غير منقولة بعد؟ النسخة السابقة تبقى متاحة أثناء الانتقال.
      </HandoffSurface>
    </section>
  );
}
