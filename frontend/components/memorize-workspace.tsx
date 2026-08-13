"use client";

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState, Fragment, type CSSProperties } from "react";
import { useSearchParams } from "next/navigation";
import {
  getJson,
  getJsonAccepting,
  postJson,
  type MemorizationContext,
  type MemorizationContextMap,
  type MemorizationContextSegment,
  type MushafPage,
  type Surah,
} from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  isMushafEdition,
  isReaderLayout,
  spreadPageNumbers,
  toArabicDigits,
  type MushafEditionId,
  type ReaderLayout,
} from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { useEditionFont } from "@/lib/use-edition-font";
import { topicColor, topicPathParts, type TopicWash } from "@/lib/topic-color";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { MushafStage } from "@/components/mushaf-stage";
import { MemorizePlayer } from "@/components/memorize-player";
import { ChromeField, ChromeSelect } from "@/components/tool-chrome";
import {
  Button,
  ProgressBar,
  SegmentedControl,
  StatusState,
} from "@/components/ui/primitives";

type PageResult = {
  key: string;
  page: MushafPage | null;
  error: string;
};

type SpreadResult = {
  key: string;
  right: MushafPage | null;
  left: MushafPage | null;
  error: string;
};

type ContextResult = {
  key: string;
  data: MemorizationContext | null;
};

type RangeDraft = {
  anchor: number;
  previousFrom: number;
  previousTo: number;
};

const ZOOM_MIN = 0.75;
const ZOOM_MAX = 2;
const ZOOM_STEP = 0.1;
const EMPTY_CONTEXT_SEGMENTS: MemorizationContextSegment[] = [];

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function clampZoom(value: number) {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(value * 10) / 10));
}

function verseKeysFromPage(page: MushafPage | null) {
  if (!page) return [] as string[];
  const keys: string[] = [];
  const seen = new Set<string>();
  page.lines.forEach((line) => {
    line.words.forEach((word) => {
      const surah = Number(word.surah);
      const ayah = Number(word.ayah);
      if (!Number.isInteger(surah) || !Number.isInteger(ayah) || surah < 1 || ayah < 1) return;
      const key = `${surah}:${ayah}`;
      if (seen.has(key)) return;
      seen.add(key);
      keys.push(key);
    });
  });
  return keys;
}

function contextCountLabel(value: number) {
  const count = Math.max(1, value);
  if (count === 1) return "آية واحدة";
  if (count === 2) return "آيتان";
  return `${toArabicDigits(count)} آيات`;
}

function TopicPath({
  title,
  fallback = "موضوع غير معنون",
  className,
}: {
  title?: string;
  fallback?: string;
  className?: string;
}) {
  const parts = topicPathParts(title);
  if (!parts.length) {
    return <span className={className || "mz-context-title"}>{fallback}</span>;
  }
  return (
    <span className={className || "mz-context-title"} aria-label={parts.join("، ")}>
      {parts.map((part, index) => (
        <Fragment key={`${index}-${part}`}>
          {index ? <span className="mz-context-path-separator" aria-hidden="true">←</span> : null}
          <span className="mz-context-path-part" dir="rtl">{part}</span>
        </Fragment>
      ))}
    </span>
  );
}

function mushafQuery(editionId: MushafEditionId) {
  const edition = MUSHAF_EDITIONS[editionId];
  return editionId === "azhar_amiri" || editionId === "shamarly"
    ? `?mushaf_version=${encodeURIComponent(edition.waqfSource)}`
    : "";
}

function pageFontName(editionId: MushafEditionId, page: MushafPage | null) {
  return editionId === "shamarly" && page?.glyph_mapping_mode === "shemrly-page-local"
    ? page.font_name
    : undefined;
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
  const [layout, setLayout] = useState<ReaderLayout>(() => {
    const value = searchParams.get("layout");
    return isReaderLayout(value) ? value : "dual";
  });
  const [dualAvailable, setDualAvailable] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [concealed, setConcealed] = useState(false);
  const [revealedAyah, setRevealedAyah] = useState<number | null>(null);
  const [rangeDraft, setRangeDraft] = useState<RangeDraft | null>(null);
  const [pageOverride, setPageOverride] = useState<number | null>(null);
  const [activeAudioWord, setActiveAudioWord] = useState<number | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [retryToken, setRetryToken] = useState(0);
  const [moving, setMoving] = useState(false);
  const [transportHost, setTransportHost] = useState<HTMLDivElement | null>(null);
  const [controlsHost, setControlsHost] = useState<HTMLDivElement | null>(null);
  const [pageResult, setPageResult] = useState<PageResult>({key: "", page: null, error: ""});
  const [spreadResult, setSpreadResult] = useState<SpreadResult>({key: "", right: null, left: null, error: ""});
  const [contextResult, setContextResult] = useState<ContextResult>({key: "", data: null});
  const [contextMapResult, setContextMapResult] = useState<{key: string; segments: MemorizationContextSegment[]}>({
    key: "",
    segments: [],
  });
  const edition = MUSHAF_EDITIONS[editionId];
  const dualActive = layout === "dual" && dualAvailable;
  const pageKey = pageOverride
    ? `${editionId}:page:${pageOverride}:${retryToken}`
    : `${editionId}:${surahNumber}:${activeAyah}:${retryToken}`;
  const contextKey = `${surahNumber}:${activeAyah}:${retryToken}`;
  const visiblePage = pageResult.key === pageKey ? pageResult : null;
  const focusPage = visiblePage?.page?.page_number || pageOverride;
  const [rightPageNumber, leftPageNumber] = focusPage && dualActive
    ? spreadPageNumbers(focusPage, edition.minPage, edition.maxPage)
    : [null, null];
  const spreadKey = dualActive && focusPage
    ? `${editionId}:${rightPageNumber || 0}:${leftPageNumber || 0}:${retryToken}`
    : "";
  const visibleSpread = spreadResult.key === spreadKey ? spreadResult : null;
  const rightPage = dualActive
    ? (visiblePage?.page?.page_number === rightPageNumber ? visiblePage.page : visibleSpread?.right || null)
    : null;
  const leftPage = dualActive
    ? (visiblePage?.page?.page_number === leftPageNumber ? visiblePage.page : visibleSpread?.left || null)
    : null;
  const fontLoading = useEditionFont(editionId, pageFontName(editionId, visiblePage?.page || null));
  const rightFontLoading = useEditionFont(editionId, pageFontName(editionId, rightPage));
  const leftFontLoading = useEditionFont(editionId, pageFontName(editionId, leftPage));
  const visibleContext = contextResult.key === contextKey ? contextResult.data : null;
  const contextLoading = contextResult.key !== contextKey;
  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const contextRange = useMemo(() => {
    if (!visibleContext?.found || visibleContext.from?.surah !== surahNumber || visibleContext.to?.surah !== surahNumber) {
      return undefined;
    }
    return [visibleContext.from.ayah, visibleContext.to.ayah] as const;
  }, [surahNumber, visibleContext]);
  const contextPosition = contextRange
    ? Math.max(1, Math.min(contextRange[1] - contextRange[0] + 1, activeAyah - contextRange[0] + 1))
    : 1;
  const contextLength = contextRange ? contextRange[1] - contextRange[0] + 1 : Math.max(1, visibleContext?.run_length || 1);
  const activeTopicColor = visibleContext?.found
    ? topicColor(visibleContext.topic_id, visibleContext.title)
    : undefined;
  const visibleVerseKeys = useMemo(() => {
    const pages = dualActive ? [rightPage, leftPage] : [visiblePage?.page || null];
    const keys: string[] = [];
    const seen = new Set<string>();
    pages.forEach((page) => {
      verseKeysFromPage(page).forEach((key) => {
        if (seen.has(key)) return;
        seen.add(key);
        keys.push(key);
      });
    });
    return keys.slice(0, 100);
  }, [dualActive, leftPage, rightPage, visiblePage?.page]);
  const verseKeyList = visibleVerseKeys.join(",");
  const contextSegments = contextMapResult.key === verseKeyList
    ? contextMapResult.segments
    : EMPTY_CONTEXT_SEGMENTS;
  const contextByKey = useMemo(() => {
    const map = new Map<string, TopicWash>();
    contextSegments.forEach((segment) => {
      const color = topicColor(segment.topic_id, segment.title);
      (segment.verse_keys || []).forEach((key) => {
        map.set(key, {color, segmentId: segment.segment_id});
      });
    });
    if (visibleContext?.found && contextRange) {
      const color = topicColor(visibleContext.topic_id, visibleContext.title);
      for (let ayah = contextRange[0]; ayah <= contextRange[1]; ayah += 1) {
        const key = `${surahNumber}:${ayah}`;
        if (!map.has(key)) map.set(key, {color, segmentId: 0});
      }
    }
    return map;
  }, [contextRange, contextSegments, surahNumber, visibleContext]);
  const legendTopics = useMemo(() => {
    const unique: Array<MemorizationContextSegment & {color: string}> = [];
    const seen = new Set<string>();
    contextSegments.forEach((segment) => {
      const identity = `${segment.topic_id}|${segment.title}`;
      if (seen.has(identity)) return;
      seen.add(identity);
      unique.push({...segment, color: topicColor(segment.topic_id, segment.title)});
    });
    return unique;
  }, [contextSegments]);
  const contextRangeText = visibleContext?.found
    ? (
      visibleContext.same_surah && visibleContext.from && visibleContext.to && visibleContext.from.surah === visibleContext.to.surah
        ? `${selectedSurah?.name || `سورة ${toArabicDigits(visibleContext.from.surah)}`} · ${
          visibleContext.from.ayah === visibleContext.to.ayah
            ? toArabicDigits(visibleContext.from.ayah)
            : `${toArabicDigits(visibleContext.from.ayah)}–${toArabicDigits(visibleContext.to.ayah)}`
        } · ${contextCountLabel(visibleContext.run_length || contextLength)}`
        : `${visibleContext.label || ""} · ${contextCountLabel(visibleContext.run_length || contextLength)}`.replace(/^\s*·\s*|\s*·\s*$/g, "")
    )
    : "";
  const picking = rangeDraft !== null;
  const visualRange = picking
    ? [rangeDraft.anchor, rangeDraft.anchor] as const
    : [fromAyah, toAyah] as const;
  const pageStep = dualActive ? 2 : 1;
  const atFirstPage = !focusPage || focusPage <= edition.minPage;
  const atLastPage = !focusPage || focusPage >= edition.maxPage - (dualActive ? 1 : 0);

  const updateActiveAyah = useCallback((ayah: number) => {
    setActiveAyah(ayah);
    setActiveAudioWord(null);
    setPageOverride(null);
  }, []);

  const loadAyahNumbers = useCallback(async (surah: number, signal?: AbortSignal) => {
    const cached = ayahCache.current.get(surah);
    if (cached) return cached;
    const numbers = await getJson<number[]>(`/backend-api/surahs/${surah}/ayahs`, signal);
    ayahCache.current.set(surah, numbers);
    return numbers;
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1100px)");
    const update = () => setDualAvailable(media.matches);
    update();
    media.addEventListener("change", update);
    const hasLayoutParam = new URL(window.location.href).searchParams.has("layout");
    const frame = window.requestAnimationFrame(() => {
      const savedZoom = Number(window.localStorage.getItem("athar-memorize-zoom") || window.localStorage.getItem("mz_zoom"));
      if (Number.isFinite(savedZoom)) setZoom(clampZoom(savedZoom));
      const savedLayout = window.localStorage.getItem("athar-memorize-layout");
      if (!hasLayoutParam && isReaderLayout(savedLayout)) setLayout(savedLayout);
    });
    return () => {
      media.removeEventListener("change", update);
      window.cancelAnimationFrame(frame);
    };
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
    const query = mushafQuery(editionId);
    const path = pageOverride
      ? `/backend-api/${edition.apiBase}/page/${pageOverride}${query}`
      : `/backend-api/${edition.apiBase}/page-by-ayah/${surahNumber}/${activeAyah}${query}`;
    getJson<MushafPage>(path, controller.signal)
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
  }, [edition.apiBase, editionId, surahNumber, activeAyah, pageOverride, retryToken, pageKey]);

  useEffect(() => {
    if (!dualActive || !visiblePage?.page || !spreadKey) return;
    const controller = new AbortController();
    const query = mushafQuery(editionId);
    const loadPage = (pageNumber: number | null) => {
      if (!pageNumber) return Promise.resolve(null);
      if (visiblePage.page?.page_number === pageNumber) return Promise.resolve(visiblePage.page);
      return getJson<MushafPage>(
        `/backend-api/${edition.apiBase}/page/${pageNumber}${query}`,
        controller.signal,
      );
    };
    Promise.all([loadPage(rightPageNumber), loadPage(leftPageNumber)])
      .then(([right, left]) => setSpreadResult({key: spreadKey, right, left, error: ""}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setSpreadResult({
          key: spreadKey,
          right: null,
          left: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل صفحتي المصحف.",
        });
      });
    return () => controller.abort();
  }, [dualActive, edition.apiBase, editionId, leftPageNumber, rightPageNumber, spreadKey, visiblePage?.page]);

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
    if (!verseKeyList) return;
    const keys = verseKeyList.split(",");
    const controller = new AbortController();
    postJson<MemorizationContextMap>(
      "/backend-api/memorization/context-map",
      {verse_keys: keys},
      controller.signal,
    )
      .then((payload) => setContextMapResult({
        key: verseKeyList,
        segments: Array.isArray(payload.segments) ? payload.segments : [],
      }))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setContextMapResult({key: verseKeyList, segments: []});
      });
    return () => controller.abort();
  }, [verseKeyList]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("from", String(fromAyah));
    url.searchParams.set("to", String(toAyah));
    url.searchParams.set("edition", editionId);
    url.searchParams.set("layout", layout);
    url.searchParams.delete("ayah");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    window.localStorage.setItem("athar-memorize-range", `${surahNumber}:${fromAyah}:${toAyah}`);
    window.localStorage.setItem("athar-memorize-layout", layout);
  }, [surahNumber, fromAyah, toAyah, editionId, layout]);

  useEffect(() => {
    window.localStorage.setItem("athar-memorize-zoom", String(zoom));
  }, [zoom]);

  const retry = useCallback(() => {
    setCatalogError("");
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  }, [surahNumber]);

  const cancelRangePick = useCallback(() => {
    if (!rangeDraft) return false;
    setFromAyah(rangeDraft.previousFrom);
    setToAyah(rangeDraft.previousTo);
    updateActiveAyah(rangeDraft.previousFrom);
    setRangeDraft(null);
    return true;
  }, [rangeDraft, updateActiveAyah]);

  const handleAyahClick = (surah: number, ayah: number) => {
    if (concealed) {
      setRevealedAyah(ayah);
      return;
    }
    if (surah !== surahNumber) {
      setRangeDraft({anchor: ayah, previousFrom: 1, previousTo: 1});
      setSurahNumber(surah);
      setFromAyah(ayah);
      setToAyah(ayah);
      updateActiveAyah(ayah);
      return;
    }
    if (!rangeDraft) {
      setRangeDraft({anchor: ayah, previousFrom: fromAyah, previousTo: toAyah});
      setFromAyah(ayah);
      setToAyah(ayah);
      updateActiveAyah(ayah);
      return;
    }
    const start = Math.min(rangeDraft.anchor, ayah);
    const end = Math.max(rangeDraft.anchor, ayah);
    setFromAyah(start);
    setToAyah(end);
    setRangeDraft(null);
    updateActiveAyah(start);
  };

  const selectSurah = (nextSurah: number) => {
    setRangeDraft(null);
    setSurahNumber(nextSurah);
    setFromAyah(1);
    setToAyah(1);
    updateActiveAyah(1);
  };

  const selectFrom = (nextFrom: number) => {
    setRangeDraft(null);
    const nextTo = Math.max(nextFrom, toAyah);
    setFromAyah(nextFrom);
    setToAyah(nextTo);
    updateActiveAyah(nextFrom);
  };

  const selectTo = (nextTo: number) => {
    setRangeDraft(null);
    setToAyah(Math.max(fromAyah, nextTo));
    if (activeAyah > nextTo) updateActiveAyah(fromAyah);
  };

  const movePage = (direction: -1 | 1) => {
    if (!focusPage || moving) return;
    const nextPage = focusPage + direction * pageStep;
    if (nextPage < edition.minPage || nextPage > edition.maxPage) return;
    setMoving(true);
    setPageOverride(nextPage);
    window.setTimeout(() => setMoving(false), 120);
  };

  const movePageEvent = useEffectEvent((direction: -1 | 1) => {
    movePage(direction);
  });
  const cancelRangePickEvent = useEffectEvent(() => {
    cancelRangePick();
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
        target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target?.tagName || "")
      ) return;
      if (event.key === "Escape") {
        if (document.querySelector('[role="dialog"]')) return;
        event.preventDefault();
        cancelRangePickEvent();
        return;
      }
      if (event.key === "ArrowLeft" && !atLastPage) {
        event.preventDefault();
        movePageEvent(1);
      } else if (event.key === "ArrowRight" && !atFirstPage) {
        event.preventDefault();
        movePageEvent(-1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [atFirstPage, atLastPage]);

  const rendererProps = {
    view: "page" as const,
    editionId,
    ayah: null,
    surahs,
    selectedSurah,
    surahNumber,
    ayahNumber: activeAyah,
    activeAudioWord,
    focusRange: visualRange,
    contextRange,
    contextByKey,
    concealFocused: concealed,
    draftAyah: rangeDraft?.anchor ?? null,
    picking: picking && !concealed,
    revealedAyah,
    onAyahClick: handleAyahClick,
    onRetry: retry,
  };

  const positionLabel = focusPage
    ? `${dualActive && rightPageNumber && leftPageNumber
      ? `صفحتا ${toArabicDigits(rightPageNumber)}–${toArabicDigits(leftPageNumber)}`
      : `صفحة ${toArabicDigits(focusPage)}`} · ${selectedSurah?.name || `سورة ${toArabicDigits(surahNumber)}`} · ${toArabicDigits(fromAyah)}–${toArabicDigits(toAyah)}`
    : `${selectedSurah?.name || `سورة ${toArabicDigits(surahNumber)}`} · ${toArabicDigits(fromAyah)}–${toArabicDigits(toAyah)} · الآية ${toArabicDigits(activeAyah)}`;


  return (
    <section className="mz-studio" aria-label="استوديو التثبيت">
      <header className="mz-studio-bar">
        <div className="mz-studio-mast">
          <div className="mz-studio-identity">
            <p>— تثبيت</p>
            <h1 id="mz-title">ثبّت حفظك.</h1>
          </div>
          <span className="mz-studio-range" aria-label="ملخص نطاق التثبيت">
            {selectedSurah ? `سورة ${selectedSurah.name}` : "السورة"} · {toArabicDigits(fromAyah)}–{toArabicDigits(toAyah)}
          </span>
          <div className="mz-studio-view">
            <Button
              size="sm"
              variant={concealed ? "primary" : "secondary"}
              aria-pressed={concealed}
              onClick={() => {
                setConcealed((value) => !value);
                setRevealedAyah(null);
              }}
            >
              {concealed ? "أظهر نص النطاق" : "اختبر حفظي"}
            </Button>
            {dualAvailable ? (
              <SegmentedControl
                variant="pills"
                label="عرض الصفحات"
                value={layout === "dual" ? "dual" : "single"}
                options={[
                  {value: "dual" as const, label: "صفحتان متقابلتان"},
                  {value: "single" as const, label: "صفحة واحدة"},
                ]}
                onChange={(value) => setLayout(value)}
              />
            ) : null}
            <div className="mz-studio-zoom" role="group" aria-label="تكبير المصحف">
              <Button
                size="icon"
                variant="ghost"
                className="size-8"
                aria-label="تصغير المصحف"
                disabled={zoom <= ZOOM_MIN + 0.001}
                onClick={() => setZoom((value) => clampZoom(value - ZOOM_STEP))}
              >
                −
              </Button>
              <span className="mz-studio-zoom-level" aria-label="مستوى التكبير">
                {toArabicDigits(Math.round(zoom * 100))}٪
              </span>
              <Button
                size="icon"
                variant="ghost"
                className="size-8"
                aria-label="تكبير المصحف"
                disabled={zoom >= ZOOM_MAX - 0.001}
                onClick={() => setZoom((value) => clampZoom(value + ZOOM_STEP))}
              >
                +
              </Button>
            </div>
            <Button
              size="sm"
              className="min-h-8 rounded-full px-2.5"
              variant={Math.abs(zoom - 1) < 0.001 ? "quiet" : "secondary"}
              aria-pressed={Math.abs(zoom - 1) < 0.001}
              onClick={() => setZoom(1)}
            >
              ملاءمة
            </Button>
            <a className="mz-studio-asr" href={legacyUrl(`/memorize?surah=${surahNumber}&from=${fromAyah}&to=${toAyah}`)}>
              التسميع الصوتي
            </a>
          </div>
        </div>
        <div className="mz-studio-place">
          <ChromeField label="السورة">
            <ChromeSelect className="min-w-[7.5rem]" value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
              {!surahs.length ? <option>جارٍ التحميل…</option> : null}
              {surahs.map((surah) => (
                <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
              ))}
            </ChromeSelect>
          </ChromeField>
          <ChromeField label="من آية">
            <ChromeSelect className="min-w-[3.5rem]" value={fromAyah} onChange={(event) => selectFrom(Number(event.target.value))} disabled={!ayahNumbers.length}>
              {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
            </ChromeSelect>
          </ChromeField>
          <ChromeField label="إلى آية">
            <ChromeSelect className="min-w-[3.5rem]" value={toAyah} onChange={(event) => selectTo(Number(event.target.value))} disabled={!ayahNumbers.length}>
              {ayahNumbers.filter((number) => number >= fromAyah).map((number) => (
                <option key={number} value={number}>{toArabicDigits(number)}</option>
              ))}
            </ChromeSelect>
          </ChromeField>
          <ChromeField label="طبعة المصحف">
            <ChromeSelect className="min-w-[6.75rem]" value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
              {Object.values(MUSHAF_EDITIONS).map((item) => (
                <option key={item.id} value={item.id}>{item.label}</option>
              ))}
            </ChromeSelect>
          </ChromeField>
        </div>
        <div className="mz-studio-dock">
          <div ref={setTransportHost} className="mz-studio-transport" />
          <div ref={setControlsHost} className="mz-studio-session" />
        </div>
      </header>

      <aside
        className="mz-studio-context"
        aria-live="polite"
        aria-label="التفصيل الموضوعي"
        data-state={contextLoading ? "loading" : visibleContext?.found ? "ready" : "empty"}
        style={activeTopicColor ? {"--mz-topic": activeTopicColor} as CSSProperties : undefined}
      >
        <div className="mz-context-heading">
          <span className="mz-context-kicker">التفصيل الموضوعي</span>
          {contextRangeText ? <span className="mz-context-range">{contextRangeText}</span> : null}
        </div>
        {contextLoading ? (
          <StatusState tone="loading">جارٍ تحميل التفصيل الموضوعي…</StatusState>
        ) : visibleContext?.found ? (
          <>
            <TopicPath title={visibleContext.title} />
            <div className="mz-context-progress">
              <span>تقدّمك داخل الموضوع · {toArabicDigits(contextPosition)} / {toArabicDigits(contextLength)}</span>
              <ProgressBar value={contextPosition} max={contextLength} label="موضع الآية داخل المقطع الموضوعي" />
            </div>
            {legendTopics.length >= 2 ? (
              <div className="mz-context-legend" aria-label="موضوعات الصفحة">
                {legendTopics.map((segment) => (
                  <button
                    key={`${segment.topic_id}|${segment.title}|${segment.segment_id}`}
                    type="button"
                    className="mz-context-legend-item"
                    style={{"--mz-legend-color": segment.color} as CSSProperties}
                    onClick={() => {
                      const [segmentSurah, segmentAyah] = String(segment.from).split(":").map(Number);
                      if (segmentSurah === surahNumber && Number.isInteger(segmentAyah)) {
                        updateActiveAyah(segmentAyah);
                      }
                    }}
                  >
                    <TopicPath title={segment.title} className="contents" />
                  </button>
                ))}
              </div>
            ) : null}
            {visibleContext.attribution ? <small className="mz-context-source">المصدر: {visibleContext.attribution}</small> : null}
          </>
        ) : (
          <StatusState className="justify-center">لا يتوفر تفصيل موضوعي موثّق لهذه الآية بعد.</StatusState>
        )}
      </aside>

      <div className="mz-studio-stage">
        {catalogError ? (
          <StatusState tone="error" className="absolute inset-x-4 top-4 z-30" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
            {catalogError}
          </StatusState>
        ) : null}

        <MushafStage
          fill
          view="page"
          editionId={editionId}
          pageCount={dualActive ? 2 : 1}
          zoom={zoom}
          positionLabel={positionLabel}
          previousLabel="الصفحة السابقة"
          nextLabel="الصفحة التالية"
          previousDisabled={atFirstPage}
          nextDisabled={atLastPage}
          moving={moving}
          onPrevious={() => movePage(-1)}
          onNext={() => movePage(1)}
        >
          {dualActive ? (
            <div className="reader-mushaf-spread" aria-label="صفحتان متقابلتان">
              {rightPageNumber ? (
                <MushafRenderer
                  {...rendererProps}
                  page={rightPage}
                  isLoading={!rightPage && !visibleSpread?.error}
                  error={visibleSpread?.error || ""}
                  fontLoading={rightPage === visiblePage?.page ? fontLoading : rightFontLoading}
                  dualLayout
                />
              ) : <div className="reader-facing-blank" aria-hidden="true" />}
              {leftPageNumber ? (
                <MushafRenderer
                  {...rendererProps}
                  page={leftPage}
                  isLoading={!leftPage && !visibleSpread?.error}
                  error={visibleSpread?.error || ""}
                  fontLoading={leftPage === visiblePage?.page ? fontLoading : leftFontLoading}
                  dualLayout
                />
              ) : <div className="reader-facing-blank" aria-hidden="true" />}
            </div>
          ) : (
            <MushafRenderer
              {...rendererProps}
              page={visiblePage?.page || null}
              isLoading={visiblePage === null}
              error={visiblePage?.error || ""}
              fontLoading={fontLoading}
            />
          )}
        </MushafStage>

        {picking ? (
          <p className="mz-studio-hint">اضغط آية النهاية لإكمال النطاق، أو Escape للإلغاء.</p>
        ) : null}
      </div>

      <MemorizePlayer
        surahNumber={surahNumber}
        fromAyah={fromAyah}
        toAyah={toAyah}
        activeAyah={activeAyah}
        onActiveAyahChange={updateActiveAyah}
        onWordChange={setActiveAudioWord}
        chromeHost={transportHost}
        controlsHost={controlsHost}
        playbackLocked={picking}
      />
    </section>
  );
}
