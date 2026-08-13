"use client";

import { useCallback, useEffect, useEffectEvent, useMemo, useRef, useState, Fragment, type CSSProperties, type ReactNode } from "react";
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
import { usePageTajweed } from "@/lib/use-page-tajweed";
import { topicColor, topicPathParts, type TopicWash } from "@/lib/topic-color";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { MushafStage } from "@/components/mushaf-stage";
import { MemorizePlayer } from "@/components/memorize-player";
import { AtharIcon, type AtharIconName } from "@/components/ui/athar-icon";
import {
  Button,
  CheckControl,
  ProgressBar,
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
const WAQF_SOURCES = ["المدينة الجديد", "المدينة القديم", "الشمرلي"] as const;
type WaqfSource = typeof WAQF_SOURCES[number];

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

function ToolbarPopover({
  label,
  value,
  icon,
  children,
}: {
  label: string;
  value?: string;
  icon: AtharIconName;
  children: ReactNode;
}) {
  return (
    <details name="memorize-toolbar" className="group relative shrink-0">
      <summary className="flex h-[34px] cursor-pointer list-none items-center gap-1.5 rounded-[10px] border border-athar-line bg-athar-surface px-2.5 text-xs font-bold text-athar-ink transition-colors hover:border-athar-accent hover:text-athar-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent [&::-webkit-details-marker]:hidden">
        <AtharIcon name={icon} className="size-4 shrink-0 text-athar-accent" />
        <span className="max-sm:hidden">{label}</span>
        {value ? <span className="max-w-36 truncate text-[0.68rem] font-semibold text-athar-ink-faint max-lg:hidden">{value}</span> : null}
        <span className="text-[0.6rem] text-athar-ink-faint transition-transform group-open:rotate-180" aria-hidden="true">⌄</span>
      </summary>
      <div className="absolute start-0 top-[calc(100%+8px)] z-[70] grid w-[min(330px,calc(100vw-24px))] gap-3 rounded-2xl border border-athar-line bg-athar-surface p-3 shadow-athar-lg max-sm:fixed max-sm:inset-x-3 max-sm:top-[calc(var(--bar-height)+50px)] max-sm:w-auto">
        {children}
      </div>
    </details>
  );
}

function isWaqfSource(value: unknown): value is WaqfSource {
  return WAQF_SOURCES.includes(value as WaqfSource);
}

function mushafQuery(waqfSource: WaqfSource) {
  return `?mushaf_version=${encodeURIComponent(waqfSource)}`;
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
  const [showContext, setShowContext] = useState(true);
  const [tajweedEnabled, setTajweedEnabled] = useState(false);
  const [waqfEnabled, setWaqfEnabled] = useState(true);
  const [waqfSource, setWaqfSource] = useState<WaqfSource>("المدينة الجديد");
  const [preferencesReady, setPreferencesReady] = useState(false);
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
    ? `${editionId}:${waqfSource}:page:${pageOverride}:${retryToken}`
    : `${editionId}:${waqfSource}:${surahNumber}:${activeAyah}:${retryToken}`;
  const contextKey = `${surahNumber}:${activeAyah}:${retryToken}`;
  const visiblePage = pageResult.key === pageKey ? pageResult : null;
  const focusPage = visiblePage?.page?.page_number || pageOverride;
  const [rightPageNumber, leftPageNumber] = focusPage && dualActive
    ? spreadPageNumbers(focusPage, edition.minPage, edition.maxPage)
    : [null, null];
  const spreadKey = dualActive && focusPage
    ? `${editionId}:${waqfSource}:${rightPageNumber || 0}:${leftPageNumber || 0}:${retryToken}`
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
  const tajweedAvailable = editionId !== "shamarly";
  const tajweedOn = tajweedEnabled && tajweedAvailable;
  const tajweedPages = dualActive ? [rightPage, leftPage] : [visiblePage?.page || null];
  const {segmentsByWord: tajweedSegmentsByWord, loading: tajweedLoading} = usePageTajweed(tajweedPages, tajweedOn);
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
      setTajweedEnabled(
        window.localStorage.getItem("athar-reader-tajweed") === "true" ||
        window.localStorage.getItem("quranApp_tajweedEnabled") === "true",
      );
      try {
        const savedSources = JSON.parse(window.localStorage.getItem("mz_waqf_print") || "[]");
        if (Array.isArray(savedSources) && isWaqfSource(savedSources[0])) setWaqfSource(savedSources[0]);
      } catch {
        // Ignore malformed legacy preferences and retain the Madinah-new default.
      }
      const savedWaqfVisibility = window.localStorage.getItem("quranApp_waqfVisible");
      if (savedWaqfVisibility !== null) {
        setWaqfEnabled(savedWaqfVisibility === "1" || savedWaqfVisibility === "true");
      }
      setPreferencesReady(true);
    });
    return () => {
      media.removeEventListener("change", update);
      window.cancelAnimationFrame(frame);
    };
  }, []);

  useEffect(() => {
    if (!preferencesReady) return;
    window.localStorage.setItem("athar-reader-tajweed", String(tajweedEnabled));
  }, [preferencesReady, tajweedEnabled]);

  useEffect(() => {
    if (!preferencesReady) return;
    window.localStorage.setItem("mz_waqf_print", JSON.stringify([waqfSource]));
    window.localStorage.setItem("quranApp_waqfVisible", waqfEnabled ? "1" : "");
  }, [preferencesReady, waqfEnabled, waqfSource]);

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
    const query = mushafQuery(waqfSource);
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
  }, [edition.apiBase, editionId, surahNumber, activeAyah, pageOverride, retryToken, pageKey, waqfSource]);

  useEffect(() => {
    if (!dualActive || !visiblePage?.page || !spreadKey) return;
    const controller = new AbortController();
    const query = mushafQuery(waqfSource);
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
  }, [dualActive, edition.apiBase, editionId, leftPageNumber, rightPageNumber, spreadKey, visiblePage?.page, waqfSource]);

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
    tajweedEnabled: tajweedOn,
    tajweedLoading,
    tajweedSegmentsByWord,
    waqfEnabled,
    waqfSource,
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
    <section
      className={`grid h-full min-h-0 pb-[calc(4.5rem+env(safe-area-inset-bottom))] [--mz-topic:#3d7ea6] md:pb-0 ${
        showContext ? "grid-rows-[auto_auto_minmax(0,1fr)]" : "grid-rows-[auto_minmax(0,1fr)]"
      }`}
      aria-label="استوديو التثبيت"
    >
      <header className="relative z-40 h-20 shrink-0 border-b border-athar-line bg-[color-mix(in_srgb,var(--athar-surface)_94%,transparent)] px-[clamp(8px,2vw,22px)] pb-7 backdrop-blur-[18px]">
        <h1 className="sr-only" id="mz-title">ثبّت حفظك.</h1>
        <div className="flex h-[52px] min-w-0 items-center gap-1.5">
          <ToolbarPopover label="القارئ والتكرار" icon="headphones">
            <div ref={setControlsHost} />
          </ToolbarPopover>

          <ToolbarPopover
            label="الموضع"
            icon="crosshair"
            value={`${selectedSurah?.name || "السورة"} · ${toArabicDigits(fromAyah)}–${toArabicDigits(toAyah)}`}
          >
            <span className="text-[0.68rem] font-bold text-athar-gold">نطاق التثبيت</span>
            <span className="text-sm font-bold text-athar-ink" aria-label="ملخص نطاق التثبيت">
              {selectedSurah ? `سورة ${selectedSurah.name}` : "السورة"} · {toArabicDigits(fromAyah)}–{toArabicDigits(toAyah)}
            </span>
            <div className="grid grid-cols-2 gap-2">
              <label className="col-span-2 grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
                <span>السورة</span>
                <select className="min-h-10 rounded-xl border border-athar-line bg-athar-surface px-3 text-sm text-athar-ink outline-none focus:border-athar-accent focus:ring-2 focus:ring-athar-accent/15" value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
                  {!surahs.length ? <option>جارٍ التحميل…</option> : null}
                  {surahs.map((surah) => (
                    <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
                  ))}
                </select>
              </label>
              <label className="grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
                <span>من آية</span>
                <select className="min-h-10 rounded-xl border border-athar-line bg-athar-surface px-3 text-sm text-athar-ink outline-none focus:border-athar-accent focus:ring-2 focus:ring-athar-accent/15" value={fromAyah} onChange={(event) => selectFrom(Number(event.target.value))} disabled={!ayahNumbers.length}>
                  {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
                <span>إلى آية</span>
                <select className="min-h-10 rounded-xl border border-athar-line bg-athar-surface px-3 text-sm text-athar-ink outline-none focus:border-athar-accent focus:ring-2 focus:ring-athar-accent/15" value={toAyah} onChange={(event) => selectTo(Number(event.target.value))} disabled={!ayahNumbers.length}>
                  {ayahNumbers.filter((number) => number >= fromAyah).map((number) => (
                    <option key={number} value={number}>{toArabicDigits(number)}</option>
                  ))}
                </select>
              </label>
            </div>
          </ToolbarPopover>

          <ToolbarPopover label="رسم المصحف" icon="book" value={edition.label}>
            <label className="grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
              <span>طبعة المصحف</span>
              <select className="min-h-10 rounded-xl border border-athar-line bg-athar-surface px-3 text-sm text-athar-ink outline-none focus:border-athar-accent focus:ring-2 focus:ring-athar-accent/15" value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
                {Object.values(MUSHAF_EDITIONS).map((item) => (
                  <option key={item.id} value={item.id}>{item.label}</option>
                ))}
              </select>
            </label>
            <p className="m-0 text-[0.7rem] leading-5 text-athar-ink-faint">{edition.description}</p>
            <fieldset className="grid gap-1.5 border-0 p-0">
              <legend className="text-[0.68rem] font-bold text-athar-gold">علامات الوقف من مصحف</legend>
              <div className="grid grid-cols-3 gap-1" role="radiogroup" aria-label="مصدر علامات الوقف">
                {WAQF_SOURCES.map((source) => (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={waqfSource === source}
                    className={`min-h-9 rounded-[10px] border px-1 text-[0.68rem] font-bold transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent ${
                      waqfSource === source
                        ? "border-athar-accent bg-athar-accent/8 text-athar-accent"
                        : "border-athar-line bg-athar-surface text-athar-ink-soft hover:border-athar-accent"
                    }`}
                    onClick={() => {
                      setWaqfSource(source);
                      setWaqfEnabled(true);
                    }}
                    key={source}
                  >
                    {source}
                  </button>
                ))}
              </div>
            </fieldset>
            <CheckControl
              label="إظهار علامات الوقف"
              checked={waqfEnabled}
              onChange={(event) => setWaqfEnabled(event.target.checked)}
              className="min-h-10"
            />
          </ToolbarPopover>

          <span className="mx-0.5 h-7 w-px shrink-0 bg-athar-line max-sm:hidden" aria-hidden="true" />

          <Button
            size="icon"
            variant={concealed ? "primary" : "secondary"}
            className="size-[34px] rounded-[10px] text-sm"
            aria-label={concealed ? "أظهر نص النطاق" : "اختبر حفظي"}
            title={concealed ? "أظهر نص النطاق" : "اختبر حفظي"}
            aria-pressed={concealed}
            onClick={() => {
              setConcealed((value) => !value);
              setRevealedAyah(null);
            }}
          >
            <AtharIcon name={concealed ? "eye" : "eye-off"} className="size-[17px]" />
          </Button>
          <Button
            size="icon"
            variant={showContext ? "primary" : "secondary"}
            className="size-[34px] rounded-[10px] text-sm"
            aria-label="التفصيل الموضوعي"
            title="التفصيل الموضوعي"
            aria-pressed={showContext}
            onClick={() => setShowContext((value) => !value)}
          >
            <AtharIcon name="layers" className="size-[17px]" />
          </Button>
          <Button
            size="icon"
            variant={tajweedOn ? "primary" : "secondary"}
            className="size-[34px] rounded-[10px]"
            aria-label={tajweedLoading ? "جارٍ تحميل تلوين التجويد" : "تلوين التجويد"}
            title={editionId === "shamarly" ? "التلوين الحرفي غير متاح مع خط الشمرلي" : "تلوين أحكام التجويد حرفيًا"}
            aria-pressed={tajweedOn}
            disabled={!tajweedAvailable || tajweedLoading}
            onClick={() => setTajweedEnabled((value) => !value)}
          >
            <AtharIcon name="sparkles" className="size-[17px]" />
          </Button>
          {dualAvailable ? (
            <Button
              size="icon"
              variant="secondary"
              className="size-[34px] rounded-[10px] text-sm"
              aria-label={layout === "dual" ? "صفحتان متقابلتان" : "صفحة واحدة"}
              title={layout === "dual" ? "صفحتان متقابلتان" : "صفحة واحدة"}
              aria-pressed={layout === "dual"}
              onClick={() => setLayout((value) => value === "dual" ? "single" : "dual")}
            >
              <AtharIcon name={layout === "dual" ? "book-open" : "book"} className="size-[17px]" />
            </Button>
          ) : null}

          <a
            className="hidden h-[34px] shrink-0 items-center rounded-[10px] px-2 text-[0.7rem] font-bold text-athar-accent no-underline hover:bg-athar-accent/8 lg:inline-flex"
            href={legacyUrl(`/memorize?surah=${surahNumber}&from=${fromAyah}&to=${toAyah}`)}
          >
            التسميع الصوتي
          </a>

          <div ref={setTransportHost} className="ms-auto flex min-w-0 flex-1 justify-end" />
        </div>
        <div
          className="absolute inset-x-0 bottom-0 m-0 flex h-7 items-center justify-center gap-2 border-t border-athar-line-soft bg-athar-accent/5 px-3 text-center text-[0.72rem] font-semibold leading-none text-athar-ink-soft max-sm:justify-start max-sm:overflow-hidden max-sm:whitespace-nowrap"
          role="status"
          aria-live="polite"
        >
          <AtharIcon name="mouse-pointer" className="size-3.5 shrink-0 text-athar-accent" />
          <span className="truncate">
            {picking
              ? `بدأ النطاق من الآية ${toArabicDigits(rangeDraft.anchor)}؛ اضغط آية النهاية لإكماله.`
              : "اضغط آية البداية، ثم آية النهاية. اضغط ▶ للتشغيل."}
          </span>
          {picking ? (
            <button
              type="button"
              className="pointer-events-auto shrink-0 rounded-md border border-athar-line px-1.5 py-0.5 text-[0.65rem] font-bold text-athar-accent hover:border-athar-accent"
              onClick={cancelRangePick}
            >
              إلغاء
            </button>
          ) : null}
        </div>
      </header>

      {showContext ? (
        <aside
          className="relative z-20 mx-auto my-2 grid w-[min(1040px,calc(100%_-_112px))] grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2.5 rounded-xl border border-s-[3px] border-[color-mix(in_srgb,var(--mz-topic)_28%,var(--athar-line))] border-s-[var(--mz-topic)] bg-[color-mix(in_srgb,var(--mz-topic)_6%,var(--athar-surface))] px-3 py-2 shadow-[0_8px_24px_-22px_color-mix(in_srgb,var(--athar-ink)_45%,transparent)] max-sm:w-[calc(100%_-_12px)] max-sm:grid-cols-[auto_minmax(0,1fr)] max-sm:px-2"
          aria-live="polite"
          aria-label="التفصيل الموضوعي"
          data-state={contextLoading ? "loading" : visibleContext?.found ? "ready" : "empty"}
          style={activeTopicColor ? {"--mz-topic": activeTopicColor} as CSSProperties : undefined}
        >
          <span className="grid size-[34px] place-items-center rounded-[10px] bg-[color-mix(in_srgb,var(--mz-topic)_16%,transparent)] text-[var(--mz-topic)]" aria-hidden="true">
            <AtharIcon name="layers" className="size-[17px]" />
          </span>
          <div className="grid min-w-0 gap-0.5">
            <div className="mz-context-heading">
              <span className="mz-context-kicker">التفصيل الموضوعي</span>
              {contextRangeText ? <span className="mz-context-range">{contextRangeText}</span> : null}
            </div>
            {contextLoading ? (
              <StatusState tone="loading" className="min-h-8 border-0 bg-transparent p-0">جارٍ تحميل التفصيل الموضوعي…</StatusState>
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
              <span className="text-xs text-athar-ink-soft">لا يتوفر تفصيل موضوعي موثّق لهذه الآية بعد.</span>
            )}
          </div>
          {contextRange ? (
            <Button
              size="sm"
              variant="primary"
              className="min-h-8 whitespace-nowrap text-[0.7rem] max-sm:col-start-2 max-sm:w-max"
              onClick={() => {
                setRangeDraft(null);
                setFromAyah(contextRange[0]);
                setToAyah(contextRange[1]);
                updateActiveAyah(contextRange[0]);
              }}
            >
              اعتمد المقطع للحفظ
            </Button>
          ) : null}
        </aside>
      ) : null}

      <div className="relative min-h-0 overflow-hidden">
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

        <div className="absolute bottom-2 start-2 z-[25] flex items-center gap-0.5 rounded-full border border-athar-line bg-[color-mix(in_srgb,var(--athar-surface)_92%,transparent)] p-0.5 shadow-athar-sm backdrop-blur-lg" role="group" aria-label="تكبير المصحف">
          <Button
            size="icon"
            variant="ghost"
            className="size-9"
            aria-label="تصغير المصحف"
            disabled={zoom <= ZOOM_MIN + 0.001}
            onClick={() => setZoom((value) => clampZoom(value - ZOOM_STEP))}
          >
            <AtharIcon name="zoom-out" className="size-[17px]" />
          </Button>
          <span className="min-w-10 text-center text-[0.68rem] font-bold tabular-nums text-athar-ink-soft max-sm:hidden" aria-label="مستوى التكبير">
            {toArabicDigits(Math.round(zoom * 100))}٪
          </span>
          <Button
            size="icon"
            variant="ghost"
            className="size-9"
            aria-label="تكبير المصحف"
            disabled={zoom >= ZOOM_MAX - 0.001}
            onClick={() => setZoom((value) => clampZoom(value + ZOOM_STEP))}
          >
            <AtharIcon name="zoom-in" className="size-[17px]" />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="size-9 text-[0.68rem]"
            aria-label="ملاءمة"
            title="ملاءمة صفحة المصحف للشاشة"
            aria-pressed={Math.abs(zoom - 1) < 0.001}
            onClick={() => setZoom(1)}
          >
            <AtharIcon name="scan" className="size-[17px]" />
          </Button>
        </div>

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
