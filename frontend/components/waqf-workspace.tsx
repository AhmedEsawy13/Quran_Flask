"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getJson,
  type ClassicalWaqfPayload,
  type SearchHit,
  type SearchPayload,
  type Surah,
  type TawjihPayload,
  type WaqfPayload,
} from "@/lib/api";
import {cn} from "@/lib/cn";
import { toArabicDigits } from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { useBoundedAudio } from "@/lib/use-bounded-audio";
import { classicalGradeMeta, majorityWaqfSymbol, tawjihSpanCoversWpos, waqfMarkCanonical, waqfMarkGlyph, waqfMarkLabel } from "@/lib/waqf";
import { arabicWordQuery, parseVerseSearch } from "@/lib/waqf-search";
import {
  ChromeField,
  ChromeInput,
  ChromePill,
  ChromeSelect,
  ChromeStepper,
  ToolCard,
  ToolCardHead,
  ToolChrome,
  ToolIntro,
  ToolStack,
} from "@/components/tool-chrome";
import { TawjihEntryCard } from "@/components/waqf-tawjih";
import { Button, StatusState } from "@/components/ui/primitives";
import { introLinkClassName } from "@/lib/ui";

type WaqfResult = {
  key: string;
  data: WaqfPayload | null;
  classical: ClassicalWaqfPayload | null;
  tawjih: TawjihPayload | null;
  error: string;
};

function typingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  const role = target.getAttribute("role");
  return role === "combobox" || Boolean(target.closest("[role='combobox']"));
}

function scrollToComparison() {
  document.getElementById("waqf-comparison")?.scrollIntoView({block: "nearest"});
}

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function isNativeAudio(url: string | null) {
  return Boolean(url && !/youtu(?:\.be|be\.com)/i.test(url));
}

export function WaqfWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialSurah = Math.min(114, positiveInteger(searchParams.get("surah"), 2));
  const initialAyah = positiveInteger(searchParams.get("ayah"), 255);
  const initialWpos = searchParams.has("wpos")
    ? Number(searchParams.get("wpos"))
    : Number.NaN;
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(initialSurah);
  const [ayahNumber, setAyahNumber] = useState(initialAyah);
  const [selectedStopWpos, setSelectedStopWpos] = useState<number | null>(null);
  const [openImamKey, setOpenImamKey] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [catalogError, setCatalogError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchHits, setSearchHits] = useState<SearchHit[] | null>(null);
  const [searchError, setSearchError] = useState("");
  const [activeHit, setActiveHit] = useState(-1);
  const [result, setResult] = useState<WaqfResult>({key: "", data: null, classical: null, tawjih: null, error: ""});
  const {audioRef, playingKey, play, stop} = useBoundedAudio();
  const requestKey = `${surahNumber}:${ayahNumber}:${retryToken}`;
  const visible = result.key === requestKey ? result : null;
  const data = visible?.data || null;
  const classical = visible?.classical || null;
  const tawjih = visible?.tawjih || null;
  const tawjihLinked = useMemo(() => {
    const linked = new Set<number>();
    for (const entry of tawjih?.entries || []) {
      const last = Math.max(0, entry.wpos);
      for (let index = 0; index <= last; index += 1) {
        if (tawjihSpanCoversWpos(entry, index)) linked.add(index);
      }
    }
    return linked;
  }, [tawjih]);
  const selectedSurah = surahs.find((surah) => surah.number === surahNumber);
  const searchBoxRef = useRef<HTMLDivElement>(null);
  const searchGen = useRef(0);
  const parsedSearch = useMemo(() => parseVerseSearch(searchQuery, surahs), [searchQuery, surahs]);
  const canWordSearch = !parsedSearch && arabicWordQuery(searchQuery).length >= 2;
  const resultsOpen = searchOpen && canWordSearch && searchHits !== null;

  const marksByWpos = useMemo(() => {
    const marks = new Map<number, Array<{mushaf: string; symbol: string}>>();
    data?.mushafs.forEach((mushaf) => mushaf.marks.forEach((mark) => {
      const items = marks.get(mark.wpos) || [];
      items.push({mushaf: mushaf.name, symbol: mark.symbol});
      marks.set(mark.wpos, items);
    }));
    return marks;
  }, [data]);

  const unionByWpos = useMemo(
    () => new Map((data?.union_stops || []).map((stopItem) => [stopItem.wpos, stopItem])),
    [data],
  );

  const stopPositions = useMemo(() => {
    const positions = new Set<number>([...unionByWpos.keys(), ...marksByWpos.keys()]);
    return [...positions].sort((a, b) => a - b);
  }, [unionByWpos, marksByWpos]);

  useEffect(() => {
    if (!data || selectedStopWpos !== null || !stopPositions.length) return;
    setSelectedStopWpos(stopPositions[0]);
  }, [data, selectedStopWpos, stopPositions]);

  useEffect(() => {
    setOpenImamKey(null);
  }, [selectedStopWpos, surahNumber, ayahNumber]);

  const selectedUnion = selectedStopWpos === null ? null : unionByWpos.get(selectedStopWpos) || null;
  const selectedMarks = selectedStopWpos === null ? [] : marksByWpos.get(selectedStopWpos) || [];
  const selectedClassical = classical?.entries.filter((entry) => entry.wpos === selectedStopWpos) || [];
  const selectedTawjih = useMemo(() => {
    if (selectedStopWpos === null) return [];
    return (tawjih?.entries || []).filter((entry) => tawjihSpanCoversWpos(entry, selectedStopWpos));
  }, [tawjih, selectedStopWpos]);

  const bestStops = useMemo(() => {
    if (!data) return [];
    const strengths = new Map(data.union_stops.map((stopItem) => [stopItem.wpos, stopItem.count]));
    data.reciters.forEach((reciter) => {
      data.per_reciter[reciter.id]?.repeats.forEach((repeat) => {
        strengths.set(repeat.from_wpos, (strengths.get(repeat.from_wpos) || 0) + 1);
      });
    });
    const majority = Math.floor(data.reciters_total / 2) + 1;
    return [...strengths.entries()]
      .filter(([wpos]) => wpos < data.words.length - 1)
      .map(([wpos, count]) => ({wpos, count, mushaf: marksByWpos.has(wpos)}))
      .filter((item) => item.count >= majority || item.mushaf)
      .sort((a, b) => b.count - a.count || Number(b.mushaf) - Number(a.mushaf) || a.wpos - b.wpos)
      .slice(0, 6);
  }, [data, marksByWpos]);

  useEffect(() => {
    const tab = searchParams.get("tab");
    const family = searchParams.get("family");
    if (!tab && !family && searchParams.get("lab") !== "1") return;
    const dest = new URLSearchParams();
    if (tab) dest.set("tab", tab);
    if (family) dest.set("family", family);
    router.replace(`/waqf-lab${dest.toString() ? `?${dest}` : ""}`);
  }, [router, searchParams]);

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
        setAyahNumber((current) => Math.min(Math.max(1, current), numbers[numbers.length - 1]));
        setCatalogError("");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAyahNumbers([]);
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تحميل آيات السورة.");
      });
    return () => controller.abort();
  }, [surahNumber, retryToken, loadAyahNumbers]);

  useEffect(() => {
    const controller = new AbortController();
    stop();
    Promise.all([
      getJson<WaqfPayload>(`/backend-api/waqf/${surahNumber}/${ayahNumber}`, controller.signal),
      getJson<ClassicalWaqfPayload>(`/backend-api/classical-waqf/${surahNumber}/${ayahNumber}`, controller.signal)
        .catch(() => null),
      getJson<TawjihPayload>(`/backend-api/tawjih/${surahNumber}/${ayahNumber}`, controller.signal)
        .catch(() => null),
    ])
      .then(([waqf, classicalPayload, tawjihPayload]) => {
        const firstStop = [...new Set([
          ...waqf.union_stops.map((stopItem) => stopItem.wpos),
          ...waqf.mushafs.flatMap((mushaf) => mushaf.marks.map((mark) => mark.wpos)),
        ])].sort((a, b) => a - b)[0];
        setResult({key: requestKey, data: waqf, classical: classicalPayload, tawjih: tawjihPayload, error: ""});
        setSelectedStopWpos(
          Number.isInteger(initialWpos) && initialWpos >= 0 && initialWpos < waqf.words.length
            ? initialWpos
            : firstStop ?? null,
        );
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setResult({
          key: requestKey,
          data: null,
          classical: null,
          tawjih: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل دليل الوقف.",
        });
      });
    return () => controller.abort();
  }, [surahNumber, ayahNumber, retryToken, requestKey, stop, initialWpos]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("ayah", String(ayahNumber));
    if (selectedStopWpos !== null && Number.isInteger(selectedStopWpos)) {
      url.searchParams.set("wpos", String(selectedStopWpos));
    } else if (visible) {
      url.searchParams.delete("wpos");
    }
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [surahNumber, ayahNumber, selectedStopWpos, visible]);

  useEffect(() => {
    const wordQuery = arabicWordQuery(searchQuery);
    if (!searchQuery.trim() || parsedSearch || wordQuery.length < 2) {
      searchGen.current += 1;
      return;
    }
    const generation = ++searchGen.current;
    const timer = window.setTimeout(() => {
      getJson<SearchPayload>(`/backend-api/search?q=${encodeURIComponent(searchQuery)}&limit=8`)
        .then((payload) => {
          if (generation !== searchGen.current) return;
          setSearchHits(payload.results);
          setSearchOpen(true);
          setSearchError("");
          setActiveHit(-1);
        })
        .catch((reason: unknown) => {
          if (generation !== searchGen.current) return;
          setSearchHits([]);
          setSearchOpen(true);
          setSearchError(reason instanceof Error ? reason.message : "تعذّر البحث الآن");
        });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [parsedSearch, searchQuery]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (!searchBoxRef.current?.contains(event.target as Node)) setSearchOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  const navigateTo = (surah: number, ayah: number) => {
    stop();
    setSurahNumber(Math.min(114, Math.max(1, surah)));
    setAyahNumber(Math.max(1, ayah));
    setSearchQuery("");
    setSearchOpen(false);
    setSearchHits(null);
    setActiveHit(-1);
  };

  const submitSearch = () => {
    if (activeHit >= 0 && searchHits?.[activeHit]) {
      const hit = searchHits[activeHit];
      navigateTo(hit.surah_number, hit.ayah_number);
      return;
    }
    if (parsedSearch) {
      if (parsedSearch.surah < 1 || parsedSearch.surah > 114) return;
      navigateTo(parsedSearch.surah, parsedSearch.ayah);
    }
  };

  const selectSurah = (nextSurah: number) => {
    stop();
    setSurahNumber(nextSurah);
    setAyahNumber(1);
  };

  const stepAyah = async (delta: -1 | 1) => {
    const lastAyah = ayahNumbers[ayahNumbers.length - 1] || 1;
    const nextAyah = ayahNumber + delta;
    if (nextAyah >= 1 && nextAyah <= lastAyah) {
      setAyahNumber(nextAyah);
      return;
    }
    if (delta < 0 && surahNumber > 1) {
      const previousSurah = surahNumber - 1;
      const numbers = await loadAyahNumbers(previousSurah);
      stop();
      setSurahNumber(previousSurah);
      setAyahNumber(numbers[numbers.length - 1] || 1);
      return;
    }
    if (delta > 0 && surahNumber < 114) {
      stop();
      setSurahNumber(surahNumber + 1);
      setAyahNumber(1);
    }
  };

  const selectStop = (wpos: number) => {
    setSelectedStopWpos(wpos);
    scrollToComparison();
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (typingTarget(event.target)) return;
      if (event.key === "j" || event.key === "ك" || event.key === "ArrowDown") {
        event.preventDefault();
        void stepAyah(1);
        return;
      }
      if (event.key === "k" || event.key === "ل" || event.key === "ArrowUp") {
        event.preventDefault();
        void stepAyah(-1);
        return;
      }
      if (event.key === "[" || event.key === "]") {
        if (!stopPositions.length) return;
        event.preventDefault();
        const current = selectedStopWpos === null ? -1 : stopPositions.indexOf(selectedStopWpos);
        if (event.key === "]") {
          const next = current < 0 ? 0 : Math.min(stopPositions.length - 1, current + 1);
          selectStop(stopPositions[next]);
        } else {
          const previous = current < 0 ? 0 : Math.max(0, current - 1);
          selectStop(stopPositions[previous]);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedStopWpos, stopPositions, surahNumber, ayahNumber, ayahNumbers]);

  const playReciterStop = (reciterId: string, wpos: number) => {
    const detail = data?.per_reciter[reciterId];
    if (!detail?.audio_url) return;
    const stops = [...detail.stops].sort((a, b) => a.wpos - b.wpos);
    const index = stops.findIndex((stopItem) => stopItem.wpos === wpos);
    if (index < 0) return;
    const start = index > 0 ? stops[index - 1].time : 0;
    void play({
      key: `stop:${reciterId}:${wpos}`,
      source: detail.audio_url,
      start: detail.verse_start + start,
      end: detail.verse_start + stops[index].time,
    });
  };

  const retry = () => {
    setCatalogError("");
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  };
  return (
    <div aria-label="مساحة مُكْث لدراسة الوقف">
      <ToolIntro
        kicker="— مُكْث"
        title="علامة المصحــف، ووقف القارئ، وقول الإمام."
        titleId="wq-title"
        titleAriaLabel="علامة المصحف، ووقف القارئ، وقول الإمام."
        lede="هذا تميّز أثَر: ثلاث شهادات على موضع الوقف — ثم ابنِ قراءةً تناسب نَفَسك."
      >
        <a className={introLinkClassName()} href="/waqf-lab">مختبر الوقف</a>
        <a className={introLinkClassName()} href={`/waqf-practice?surah=${surahNumber}&from=${ayahNumber}&to=${ayahNumber}`}>
          تدرّب على هذا الموضع
        </a>
        <a
          className={introLinkClassName()}
          href={legacyUrl(`/mushaf-editor?edition=${encodeURIComponent("قطر")}&surah=${surahNumber}&ayah=${ayahNumber}`)}
        >
          محرّر الوقف
        </a>
      </ToolIntro>
      <audio ref={audioRef} preload="metadata" className="hidden" />

      <ToolChrome
        label="اختيار موضع الدراسة"
        pill={selectedSurah ? (
          <ChromePill>سورة <b>{selectedSurah.name}</b> · {toArabicDigits(ayahNumber)}</ChromePill>
        ) : undefined}
      >
        <ChromeField label="السورة">
          <ChromeSelect
            value={surahNumber}
            aria-label="السورة"
            onChange={(event) => selectSurah(Number(event.target.value))}
            disabled={!surahs.length}
          >
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => (
              <option key={surah.number} value={surah.number}>
                {toArabicDigits(surah.number)}. {surah.name}
              </option>
            ))}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="الآية">
          <ChromeSelect
            value={ayahNumber}
            aria-label="الآية"
            onChange={(event) => {
              stop();
              setAyahNumber(Number(event.target.value));
            }}
            disabled={!ayahNumbers.length}
          >
            {ayahNumbers.map((number) => (
              <option key={number} value={number}>{toArabicDigits(number)}</option>
            ))}
          </ChromeSelect>
        </ChromeField>
        <div className="relative min-w-[16rem] flex-[1.4] self-end max-md:min-w-0 max-md:basis-full" ref={searchBoxRef}>
          <ChromeField label="البحث عن آية" className="w-full max-md:min-w-0">
            <ChromeInput
              id="waqf-verse-search"
              role="combobox"
              aria-label="البحث عن آية"
              aria-autocomplete="list"
              aria-expanded={resultsOpen}
              aria-controls="waqf-search-results"
              aria-activedescendant={activeHit >= 0 ? `waqf-search-hit-${activeHit}` : undefined}
              placeholder="٢:٢٥٥ أو البقرة ٢٥٥ أو كلمات الآية"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                const hits = searchHits || [];
                if (event.key === "ArrowDown" && hits.length) {
                  event.preventDefault();
                  setSearchOpen(true);
                  setActiveHit((current) => (current + 1) % hits.length);
                } else if (event.key === "ArrowUp" && hits.length) {
                  event.preventDefault();
                  setSearchOpen(true);
                  setActiveHit((current) => current <= 0 ? hits.length - 1 : current - 1);
                } else if (event.key === "Enter") {
                  event.preventDefault();
                  submitSearch();
                } else if (event.key === "Escape") {
                  setSearchOpen(false);
                }
              }}
            />
          </ChromeField>
          {resultsOpen ? (
            <ul
              className="waqf-search-results"
              id="waqf-search-results"
              role="listbox"
              aria-label="نتائج البحث"
            >
              {searchError ? <li className="waqf-search-empty">{searchError}</li> : null}
              {!searchError && searchHits && !searchHits.length ? (
                <li className="waqf-search-empty">لا توجد نتائج لهذه الكلمات</li>
              ) : null}
              {searchHits?.map((hit, index) => {
                const name = surahs.find((surah) => surah.number === hit.surah_number)?.name;
                return (
                  <li key={hit.verse_key} role="presentation">
                    <button
                      type="button"
                      className={index === activeHit ? "is-active" : ""}
                      id={`waqf-search-hit-${index}`}
                      role="option"
                      aria-selected={index === activeHit}
                      onMouseEnter={() => setActiveHit(index)}
                      onClick={() => navigateTo(hit.surah_number, hit.ayah_number)}
                    >
                      <span>
                        سورة {name || toArabicDigits(hit.surah_number)} · آية {toArabicDigits(hit.ayah_number)}
                      </span>
                      <small>{hit.text}</small>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
        <ChromeStepper
          previousLabel="الآية السابقة"
          nextLabel="الآية التالية"
          previousDisabled={surahNumber <= 1 && ayahNumber <= 1}
          nextDisabled={!ayahNumbers.length || (surahNumber >= 114 && ayahNumber >= ayahNumbers[ayahNumbers.length - 1])}
          onPrevious={() => void stepAyah(-1)}
          onNext={() => void stepAyah(1)}
        />
      </ToolChrome>

      <ToolStack>
        {catalogError || visible?.error ? (
          <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
            {catalogError || visible?.error}
          </StatusState>
        ) : null}

        {!visible ? <StatusState tone="loading" className="min-h-24 justify-center">جارٍ تحميل دليل الوقف…</StatusState> : null}

        {data ? (
          <>
            <ToolCard raised aria-labelledby="waqf-verse-title">
              <ToolCardHead
                title={`سورة ${selectedSurah?.name || ""} · الآية ${toArabicDigits(ayahNumber)}`}
                titleId="waqf-verse-title"
                meta={`${toArabicDigits(data.reciters_total)} قارئًا · ${toArabicDigits(data.union_stops.length)} موضعًا · نحو ${toArabicDigits(Math.round(data.full_duration || 0))}ث`}
              />

              <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-athar-line-soft pb-3" aria-label="أفضل مواضع الوقف">
                <span className="text-[0.72rem] font-bold whitespace-nowrap text-athar-accent">★ أفضل مواضع الوقف</span>
                {bestStops.map((stopItem) => (
                  <button
                    type="button"
                    className={`inline-flex cursor-pointer items-center gap-1 border-0 border-s-2 bg-transparent px-2 py-0.5 text-[0.82rem] hover:border-athar-accent ${stopItem.mushaf ? "border-athar-accent" : "border-athar-line"}`}
                    key={stopItem.wpos}
                    onClick={() => setSelectedStopWpos(stopItem.wpos)}
                  >
                    <span className="font-athar-quran text-base font-bold">{data.words[stopItem.wpos]}</span>
                    <span className="text-[0.68rem] font-extrabold text-athar-accent">{toArabicDigits(Math.round(stopItem.count / data.reciters_total * 100))}٪</span>
                  </button>
                ))}
              </div>

              <div className="waqf-word-flow" dir="rtl">
                {data.words.map((word, index) => {
                  const union = unionByWpos.get(index);
                  const marks = marksByWpos.get(index) || [];
                  const isStop = Boolean(union || marks.length);
                  return (
                    <span className={`waqf-word-unit${selectedStopWpos === index ? " is-selected" : ""}${tawjihLinked.has(index) ? " is-tawjih" : ""}`} key={`${word}-${index}`}>
                      <span className="waqf-word">{word}</span>
                      {isStop ? (
                        <button
                          type="button"
                          className={`waqf-inline-stop${union?.solo ? " is-solo" : ""}`}
                          aria-label={`تفصيل الوقف بعد ${word}`}
                          onClick={() => selectStop(index)}
                        >
                          <span className="waqf-stop-icon" aria-hidden="true">Ⅱ</span>
                          {union?.solo ? (
                            <>
                              <b>انفرد</b>
                              <span>{data.per_reciter[union.reciters[0]]?.name_ar || union.reciters[0]}</span>
                            </>
                          ) : union ? <b>{toArabicDigits(union.count)}/{toArabicDigits(data.reciters_total)}</b> : <b>مصحف</b>}
                          {union ? <small>~{toArabicDigits(union.avg_duration.toFixed(1))}ث</small> : null}
                        </button>
                      ) : null}
                    </span>
                  );
                })}
              </div>

              <div className="mt-3 flex flex-wrap gap-x-[18px] gap-y-2 border-t border-athar-line-soft pt-3 text-[0.74rem] text-athar-ink-soft">
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block size-[0.8em] rounded-full bg-athar-accent" />
                  موضع وقف (كلما زاد العدد زاد الاتفاق)
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block size-[0.8em] rounded-full border-2 border-[var(--wq-solo)] bg-transparent" />
                  انفرد به قارئ واحد
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block size-[0.8em] rounded-full bg-[var(--wq-repeat)]" />
                  أعاد القارئ
                </span>
              </div>

            </ToolCard>

            <div id="waqf-comparison">
              {selectedStopWpos !== null ? (
                <div className="grid gap-3.5">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2 text-[0.84rem] text-athar-ink-soft">
                    <span>بعد كلمة</span>
                    <strong className="font-athar-quran text-[1.35rem] text-athar-ink">{data.words[selectedStopWpos]}</strong>
                    {selectedUnion?.solo ? (
                      <em className="rounded-full bg-[var(--wq-solo-soft)] px-2 py-0.5 text-[0.68rem] not-italic font-bold text-[var(--wq-solo)]">انفراد قارئ</em>
                    ) : null}
                  </div>

                  <div className="wq-stop-desk">
                    <div className="wq-score-panel">
                      <section className="wq-score-row" aria-labelledby="wq-score-mushaf">
                        <h3 className="wq-score-label" id="wq-score-mushaf">مصحف</h3>
                        <div className="wq-score-body">
                          <div className="wq-score-track">
                            {data.mushafs.map((mushaf) => {
                              const mark = mushaf.marks.find((item) => item.wpos === selectedStopWpos);
                              const majority = majorityWaqfSymbol(
                                data.mushafs
                                  .map((edition) => edition.marks.find((item) => item.wpos === selectedStopWpos)?.symbol)
                                  .filter((symbol): symbol is string => Boolean(symbol)),
                              );
                              const minority = Boolean(
                                mark && majority && waqfMarkCanonical(mark.symbol) !== majority,
                              );
                              return (
                                <div
                                  className="wq-score-mushaf"
                                  key={mushaf.id}
                                  title={mark ? `${mushaf.name} · ${waqfMarkLabel(mark.symbol)}` : mushaf.name}
                                >
                                  <span className="wq-score-mushaf-name">{mushaf.name}</span>
                                  <strong className={cn("wq-score-mushaf-glyph", !mark && "is-empty", minority && "is-minority")}>
                                    {mark ? waqfMarkGlyph(mark.symbol) : "—"}
                                  </strong>
                                </div>
                              );
                            })}
                          </div>
                          {!selectedMarks.length ? (
                            <p className="wq-score-empty">لا تحمل المصاحف المقارنة علامةً هنا.</p>
                          ) : null}
                        </div>
                      </section>

                      <section className="wq-score-row" aria-labelledby="wq-score-reciters">
                        <h3 className="wq-score-label" id="wq-score-reciters">قرّاء</h3>
                        <div className="wq-score-body">
                          <div className="wq-score-track" role="list">
                            {data.reciters.map((reciter) => {
                              const detail = data.per_reciter[reciter.id];
                              const name = reciter.name_ar || detail?.name_ar || reciter.id;
                              const stopped = Boolean(
                                selectedUnion?.reciters.includes(reciter.id)
                                || detail?.stops.some((item) => item.wpos === selectedStopWpos),
                              );
                              const native = isNativeAudio(detail?.audio_url || null);
                              const playable = stopped && native;
                              const key = `stop:${reciter.id}:${selectedStopWpos}`;
                              return (
                                <button
                                  type="button"
                                  role="listitem"
                                  className={cn(
                                    "wq-score-dot",
                                    stopped && "is-stop",
                                    stopped && selectedUnion?.solo && "is-solo",
                                    playingKey === key && "is-playing",
                                    !native && "is-muted",
                                  )}
                                  key={reciter.id}
                                  title={name}
                                  aria-label={name}
                                  disabled={!playable}
                                  onClick={() => playReciterStop(reciter.id, selectedStopWpos)}
                                />
                              );
                            })}
                          </div>
                          {(() => {
                            const stopped = data.reciters.filter((reciter) => {
                              const detail = data.per_reciter[reciter.id];
                              return selectedUnion?.reciters.includes(reciter.id)
                                || Boolean(detail?.stops.some((item) => item.wpos === selectedStopWpos));
                            });
                            if (!stopped.length) {
                              return <p className="wq-score-empty">لم يقف قارئ مسجّل في هذا الموضع.</p>;
                            }
                            const audience = stopped.find((reciter) => isNativeAudio(data.per_reciter[reciter.id]?.audio_url || null));
                            return (
                              <p className="wq-score-caption">
                                {toArabicDigits(stopped.length)} وقفوا
                                {audience ? (
                                  <>
                                    {" · "}
                                    <button
                                      type="button"
                                      className="wq-score-listen"
                                      onClick={() => playReciterStop(audience.id, selectedStopWpos)}
                                    >
                                      استمع الجمهور
                                    </button>
                                  </>
                                ) : null}
                              </p>
                            );
                          })()}
                        </div>
                      </section>

                      <section className="wq-score-row" aria-labelledby="wq-score-imams">
                        <h3 className="wq-score-label" id="wq-score-imams">أئمة</h3>
                        <div className="wq-score-body">
                          {selectedClassical.length ? (
                            <>
                              <div className="wq-score-track">
                                {selectedClassical.filter((entry, index, list) => (
                                  list.findIndex((item) => item.source === entry.source && item.grade === entry.grade) === index
                                )).map((entry) => {
                                  const key = `${entry.source}::${entry.grade}`;
                                  const source = classical?.sources[entry.source];
                                  const meta = classicalGradeMeta[entry.grade];
                                  const open = openImamKey === key;
                                  return (
                                    <button
                                      type="button"
                                      className={cn("wq-score-stamp wq-grade", meta && `is-${meta.cls}`, open && "is-open")}
                                      key={key}
                                      aria-expanded={open}
                                      title={meta?.desc || entry.grade}
                                      onClick={() => setOpenImamKey(open ? null : key)}
                                    >
                                      {source?.name || entry.source} · {entry.grade_raw || entry.grade}
                                    </button>
                                  );
                                })}
                              </div>
                              {(() => {
                                const openEntry = selectedClassical.find((entry) => `${entry.source}::${entry.grade}` === openImamKey);
                                if (!openEntry) return null;
                                const note = (openEntry.note || "").trim();
                                return (
                                  <div className="wq-score-imam-note">
                                    {openEntry.quote ? <blockquote>{openEntry.quote}</blockquote> : null}
                                    {note ? <p className="wq-illa">{note}</p> : null}
                                  </div>
                                );
                              })()}
                            </>
                          ) : (
                            <p className="wq-score-empty">لا يتوفر حكم تراثي موثّق لهذا الموضع بعد.</p>
                          )}
                        </div>
                      </section>
                    </div>

                    <section className="wq-stop-desk-tawjih" aria-labelledby="wq-score-tawjih">
                      <h3 className="wq-score-label" id="wq-score-tawjih">توجيه</h3>
                      {selectedTawjih.length ? (
                        <div className="wq-score-tawjih-body">
                          <TawjihEntryCard
                            entry={selectedTawjih[0]}
                            words={data.words}
                            author={tawjih?.source?.author || "د. أحمد صابر عبدالهادي"}
                            onSelectWpos={setSelectedStopWpos}
                          />
                          {selectedTawjih.length > 1 ? (
                            <p className="wq-score-tawjih-more">و{toArabicDigits(selectedTawjih.length - 1)} أخرى</p>
                          ) : null}
                        </div>
                      ) : (
                        <p className="wq-score-empty">لا يوجد توجيه مربوط بهذا الموضع.</p>
                      )}
                    </section>
                  </div>
                </div>
              ) : (
                <p className="m-0 text-[0.88rem] leading-relaxed text-athar-ink-soft">
                  اختر موضعًا من الآية أو من أفضل مواضع الوقف.
                </p>
              )}
            </div>
          </>
        ) : null}
      </ToolStack>
    </div>
  );
}
