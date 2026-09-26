"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ApiError,
  getJson,
  type ClassicalWaqfPayload,
  type SearchHit,
  type SearchPayload,
  type Surah,
  type TawjihPayload,
  type WaqfPayload,
  type WaqfReciterDetail,
} from "@/lib/api";
import {cn} from "@/lib/cn";
import { arabicCount, toArabicDigits } from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { useBoundedAudio } from "@/lib/use-bounded-audio";
import { isNegativeGrade, reciterPhrases, tawjihSpanCoversWpos } from "@/lib/waqf";
import { arabicWordQuery, parseVerseSearch } from "@/lib/waqf-search";
import {
  ChromeField,
  ChromeInput,
  ChromeSelect,
  ChromeStepper,
  ToolCard,
  ToolCardHead,
  ToolChrome,
  ToolIntro,
  ToolStack,
} from "@/components/tool-chrome";
import { WaqfMatrix } from "@/components/waqf-matrix";
import { WaqfReciters } from "@/components/waqf-reciters";
import { WaqfClassical } from "@/components/waqf-classical";
import { WaqfTawjih } from "@/components/waqf-tawjih";
import { WaqfStopInspector } from "@/components/waqf-stop-inspector";
import { Button, Field, SegmentedControl, SelectControl, StatusState } from "@/components/ui/primitives";
import { introLinkClassName } from "@/lib/ui";

type WaqfResult = {
  key: string;
  data: WaqfPayload | null;
  classical: ClassicalWaqfPayload | null;
  tawjih: TawjihPayload | null;
  error: string;
  /** The API has no reciter timings for this ayah yet (404) — not an outage. */
  missing?: boolean;
};

type BreathProfile = "short" | "medium" | "long";

type AyahPanel = "breath" | "matrix" | "classical" | "tawjih" | "reciters";

/** Ayah-wide views, one at a time, so the page never becomes a long scroll. */
const ayahPanels: Array<{key: AyahPanel; label: string}> = [
  {key: "breath", label: "القراءة حسب نَفَسك"},
  {key: "matrix", label: "المصاحف والقرّاء"},
  {key: "classical", label: "كتب الوقف"},
  {key: "tawjih", label: "التوجيه"},
  {key: "reciters", label: "كيف قرأها كل قارئ"},
];

type ReciterProfile = {
  id: string;
  name: string;
  detail: WaqfReciterDetail;
  longestWords: number;
  longestSeconds: number;
};

const breathLabels: Record<BreathProfile, string> = {
  short: "قصير",
  medium: "متوسط",
  long: "طويل",
};

function typingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  const role = target.getAttribute("role");
  return role === "combobox" || Boolean(target.closest("[role='combobox']"));
}

/** On narrow screens the evidence sits below the verse; bring it into view. */
function scrollToComparison() {
  if (window.matchMedia("(min-width: 1024px)").matches) return;
  document.getElementById("waqf-comparison")?.scrollIntoView({block: "nearest", behavior: "smooth"});
}

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function isNativeAudio(url: string | null) {
  return Boolean(url && !/youtu(?:\.be|be\.com)/i.test(url));
}

function reciterProfiles(data: WaqfPayload | null) {
  if (!data) return [];
  return data.reciters
    .map((reciter): ReciterProfile | null => {
      const detail = data.per_reciter[reciter.id];
      if (!detail || !isNativeAudio(detail.audio_url) || !detail.phrases.length) return null;
      let longestWords = 0;
      let longestSeconds = 0;
      detail.phrases.forEach((phrase) => {
        const wordCount = phrase.last_wpos - phrase.first_wpos + 1;
        const seconds = phrase.end - phrase.start;
        if (wordCount > longestWords || (wordCount === longestWords && seconds > longestSeconds)) {
          longestWords = wordCount;
          longestSeconds = seconds;
        }
      });
      return {id: reciter.id, name: detail.name_ar || reciter.name_ar, detail, longestWords, longestSeconds};
    })
    .filter((profile): profile is ReciterProfile => Boolean(profile))
    .sort((a, b) => a.longestWords - b.longestWords || a.longestSeconds - b.longestSeconds);
}

function recommendedProfile(profiles: ReciterProfile[], breath: BreathProfile) {
  if (!profiles.length) return null;
  if (breath === "short") return profiles[0];
  if (breath === "long") return profiles[profiles.length - 1];
  return profiles[Math.floor((profiles.length - 1) / 2)];
}

export function WaqfWorkspace() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialSurah = Math.min(114, positiveInteger(searchParams.get("surah"), 2));
  const initialAyah = positiveInteger(searchParams.get("ayah"), 255);
  // A deep-linked stop applies to the first ayah only. Reading it once also
  // keeps our own replaceState(wpos=…) from re-running the data fetch.
  const pendingWpos = useRef(searchParams.has("wpos") ? Number(searchParams.get("wpos")) : Number.NaN);
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(initialSurah);
  const [ayahNumber, setAyahNumber] = useState(initialAyah);
  const [breath, setBreath] = useState<BreathProfile>("medium");
  const [selectedReciterId, setSelectedReciterId] = useState("");
  const [selectedStopWpos, setSelectedStopWpos] = useState<number | null>(null);
  const [panel, setPanel] = useState<AyahPanel>("breath");
  const [retryToken, setRetryToken] = useState(0);
  const [catalogError, setCatalogError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchHits, setSearchHits] = useState<SearchHit[] | null>(null);
  const [searchError, setSearchError] = useState("");
  const [activeHit, setActiveHit] = useState(-1);
  const [result, setResult] = useState<WaqfResult>({key: "", data: null, classical: null, tawjih: null, error: ""});
  const {audioRef, playingKey, progress, play, stop} = useBoundedAudio();
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
  const profiles = useMemo(() => reciterProfiles(data), [data]);
  const recommended = useMemo(() => recommendedProfile(profiles, breath), [profiles, breath]);
  const selectedProfile = profiles.find((profile) => profile.id === selectedReciterId) || recommended;
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

  // Positions ruled on only by the imams or a توجيه are stops too: the ayah end
  // graded تام vs كاف, or a pause no mushaf prints, is exactly what to study.
  // A position every imam rules out («لا»، «قبيح») is a warning, not a stop.
  const scholarlyByWpos = useMemo(() => {
    const labels = new Map<number, "أئمة" | "توجيه" | "لا وقف">();
    const rulings = new Map<number, string[]>();
    (classical?.entries || []).forEach((entry) => rulings.set(entry.wpos, [...(rulings.get(entry.wpos) || []), entry.grade]));
    rulings.forEach((grades, wpos) => labels.set(wpos, grades.every(isNegativeGrade) ? "لا وقف" : "أئمة"));
    (tawjih?.entries || []).forEach((entry) => labels.set(entry.wpos, "توجيه"));
    return labels;
  }, [classical, tawjih]);
  const avoidCount = useMemo(
    () => [...scholarlyByWpos].filter(([wpos, label]) => label === "لا وقف" && !unionByWpos.has(wpos) && !marksByWpos.has(wpos)).length,
    [scholarlyByWpos, unionByWpos, marksByWpos],
  );

  const stopPositions = useMemo(() => {
    const wordCount = data?.words.length || 0;
    const positions = new Set<number>([...unionByWpos.keys(), ...marksByWpos.keys()]);
    scholarlyByWpos.forEach((_, wpos) => {
      if (wpos >= 0 && wpos < wordCount) positions.add(wpos);
    });
    return [...positions].sort((a, b) => a - b);
  }, [data, unionByWpos, marksByWpos, scholarlyByWpos]);

  // Prefer an explicit user selection; otherwise the first stop on the ayah.
  // Derived (not an effect) so eslint react-hooks/set-state-in-effect stays clean.
  const activeStopWpos =
    selectedStopWpos !== null
      ? selectedStopWpos
      : (stopPositions.length ? stopPositions[0] : null);


  const bestStops = useMemo(() => {
    if (!data) return [];
    // Distinct reciters who stop (or stop and repeat) here — never counted twice.
    const reciterSets = new Map(data.union_stops.map((stopItem) => [stopItem.wpos, new Set(stopItem.reciters)]));
    data.reciters.forEach((reciter) => {
      data.per_reciter[reciter.id]?.repeats.forEach((repeat) => {
        const set = reciterSets.get(repeat.from_wpos) || new Set<string>();
        set.add(reciter.id);
        reciterSets.set(repeat.from_wpos, set);
      });
    });
    const strengths = new Map([...reciterSets].map(([wpos, set]) => [wpos, set.size]));
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
        const nextProfiles = reciterProfiles(waqf);
        const defaultProfile = recommendedProfile(nextProfiles, "medium");
        const firstStop = [...new Set([
          ...waqf.union_stops.map((stopItem) => stopItem.wpos),
          ...waqf.mushafs.flatMap((mushaf) => mushaf.marks.map((mark) => mark.wpos)),
        ])].sort((a, b) => a - b)[0];
        setResult({key: requestKey, data: waqf, classical: classicalPayload, tawjih: tawjihPayload, error: ""});
        setSelectedReciterId((current) => nextProfiles.some((profile) => profile.id === current)
          ? current
          : defaultProfile?.id || "");
        const linked = pendingWpos.current;
        pendingWpos.current = Number.NaN;
        setSelectedStopWpos(
          Number.isInteger(linked) && linked >= 0 && linked < waqf.words.length
            ? linked
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
          missing: reason instanceof ApiError && reason.status === 404,
        });
      });
    return () => controller.abort();
  }, [surahNumber, ayahNumber, retryToken, requestKey, stop]);

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

  const stepAyah = useCallback(async (delta: -1 | 1) => {
    const lastAyah = ayahNumbers[ayahNumbers.length - 1] || 1;
    const nextAyah = ayahNumber + delta;
    if (nextAyah >= 1 && nextAyah <= lastAyah) {
      setAyahNumber(nextAyah);
      setSelectedStopWpos(null);
      return;
    }
    if (delta < 0 && surahNumber > 1) {
      const previousSurah = surahNumber - 1;
      const numbers = await loadAyahNumbers(previousSurah);
      stop();
      setSurahNumber(previousSurah);
      setAyahNumber(numbers[numbers.length - 1] || 1);
      setSelectedStopWpos(null);
      return;
    }
    if (delta > 0 && surahNumber < 114) {
      stop();
      setSurahNumber(surahNumber + 1);
      setAyahNumber(1);
      setSelectedStopWpos(null);
    }
  }, [ayahNumber, ayahNumbers, surahNumber, stop, loadAyahNumbers]);

  const showPanel = (next: AyahPanel) => {
    setPanel(next);
    window.requestAnimationFrame(() => document.getElementById("waqf-ayah-panels")?.scrollIntoView({block: "start", behavior: "smooth"}));
  };

  const selectStop = useCallback((wpos: number) => {
    setSelectedStopWpos(wpos);
    scrollToComparison();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Leave browser/OS shortcuts (Alt+←, ⌘[, Ctrl+K…) alone.
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
      if (typingTarget(event.target)) return;
      if (event.key === "j" || event.key === "ك" || event.key === "ArrowLeft") {
        event.preventDefault();
        void stepAyah(1);
        return;
      }
      if (event.key === "k" || event.key === "ل" || event.key === "ArrowRight") {
        event.preventDefault();
        void stepAyah(-1);
        return;
      }
      if (event.key === "[" || event.key === "]") {
        if (!stopPositions.length) return;
        event.preventDefault();
        const current = activeStopWpos === null ? -1 : stopPositions.indexOf(activeStopWpos);
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
  }, [activeStopWpos, stopPositions, stepAyah, selectStop]);

  const selectBreath = (nextBreath: BreathProfile) => {
    setBreath(nextBreath);
    const nextProfile = recommendedProfile(profiles, nextBreath);
    if (nextProfile) setSelectedReciterId(nextProfile.id);
  };

  const playPhrase = (phraseIndex: number) => {
    if (!selectedProfile?.detail.audio_url) return;
    const phrase = selectedProfile.detail.phrases[phraseIndex];
    if (!phrase) return;
    void play({
      key: `phrase:${selectedProfile.id}:${phraseIndex}`,
      source: selectedProfile.detail.audio_url,
      start: selectedProfile.detail.verse_start + phrase.start,
      end: selectedProfile.detail.verse_start + phrase.end,
    });
  };

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

  const playReciterPhrase = (reciterId: string, phraseIndex: number) => {
    const detail = data?.per_reciter[reciterId];
    if (!detail?.audio_url || !data) return;
    const phrase = reciterPhrases(detail, data.words.length - 1)[phraseIndex];
    if (!phrase) return;
    void play({
      key: `gallery:${reciterId}:${phraseIndex}`,
      source: detail.audio_url,
      start: detail.verse_start + phrase.start,
      end: detail.verse_start + phrase.end,
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
        kicker="مُكْث"
        tool="waqf"
        title="علامة المصحف، ووقف القارئ، وقول الإمام."
        titleId="wq-title"
        lede="ثلاث شهادات على كل موضع وقف في الآية — اضغط أي موضع لترى دليله، ثم ابنِ قراءةً تناسب نَفَسك."
      >
        {process.env.NODE_ENV === "development" ? (
          <a
            className={introLinkClassName()}
            href={legacyUrl(`/mushaf-editor?edition=${encodeURIComponent("قطر")}&surah=${surahNumber}&ayah=${ayahNumber}`)}
          >
            محرّر الوقف
          </a>
        ) : null}
      </ToolIntro>
      <audio ref={audioRef} preload="metadata" className="hidden" />

      <ToolChrome
        label="اختيار موضع الدراسة"
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
        {!catalogError && visible?.missing ? (
          <StatusState
            className="min-h-24 flex-col items-start justify-center gap-3 sm:flex-row sm:items-center sm:justify-between"
            action={<Button size="sm" variant="secondary" onClick={() => void stepAyah(1)}>الآية التالية</Button>}
          >
            لم تُحلَّل وقوف القرّاء لهذه الآية بعد. جرّب آية أخرى، أو اقرأها في المصحف مع علامات الوقف المطبوعة.
          </StatusState>
        ) : catalogError || visible?.error ? (
          <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
            {catalogError || visible?.error}
          </StatusState>
        ) : null}

        {!visible ? <StatusState tone="loading" className="min-h-24 justify-center">جارٍ تحميل دليل الوقف…</StatusState> : null}

        {data ? (
          <>
            <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(340px,1fr)]">
              <ToolCard raised aria-labelledby="waqf-verse-title">
                <ToolCardHead
                  title={`سورة ${selectedSurah?.name || ""} · الآية ${toArabicDigits(ayahNumber)}`}
                  titleId="waqf-verse-title"
                  meta={[
                    stopPositions.length - avoidCount
                      ? arabicCount(stopPositions.length - avoidCount, ["موضع وقف واحد", "موضعا وقف", "مواضع وقف", "موضع وقف"])
                      : "لا مواضع وقف",
                    avoidCount ? `${arabicCount(avoidCount, ["موضع", "موضعان", "مواضع", "موضعًا"])} نهى عنه الأئمة` : "",
                    data.reciters_total ? arabicCount(data.reciters_total, ["قارئ واحد", "قارئان", "قرّاء", "قارئًا"]) : "",
                    data.full_duration ? `نحو ${toArabicDigits(Math.round(data.full_duration))}ث` : "",
                  ].filter(Boolean).join(" · ")}
                />

                {bestStops.length ? (
                  <div className="mb-3 flex flex-wrap items-center gap-1.5 border-b border-athar-line-soft pb-3" aria-label="أفضل مواضع الوقف">
                    <span className="text-[0.72rem] font-bold whitespace-nowrap text-athar-accent">★ أفضل مواضع الوقف</span>
                    {bestStops.map((stopItem) => (
                      <button
                        type="button"
                        className={cn(
                          "inline-flex cursor-pointer items-center gap-1 rounded-e-md border-0 border-s-2 bg-transparent px-2 py-0.5 text-[0.82rem] hover:border-athar-accent hover:bg-athar-accent/5",
                          stopItem.mushaf ? "border-athar-accent" : "border-athar-line",
                          activeStopWpos === stopItem.wpos && "bg-athar-accent/10",
                        )}
                        key={stopItem.wpos}
                        aria-pressed={activeStopWpos === stopItem.wpos}
                        onClick={() => selectStop(stopItem.wpos)}
                      >
                        <span className="font-athar-quran text-base font-bold">{data.words[stopItem.wpos]}</span>
                        {data.reciters_total ? (
                          <span className="text-[0.68rem] font-extrabold text-athar-accent">{toArabicDigits(Math.round(stopItem.count / data.reciters_total * 100))}٪</span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                ) : null}

                <div className="waqf-word-flow" dir="rtl">
                  {data.words.map((word, index) => {
                    const union = unionByWpos.get(index);
                    const marks = marksByWpos.get(index) || [];
                    const scholarly = scholarlyByWpos.get(index);
                    const isStop = Boolean(union || marks.length || scholarly);
                    return (
                      <span className={`waqf-word-unit${activeStopWpos === index ? " is-selected" : ""}${tawjihLinked.has(index) ? " is-tawjih" : ""}`} key={`${word}-${index}`}>
                        <span className="waqf-word">{word}</span>
                        {isStop ? (
                          <button
                            type="button"
                            className={`waqf-inline-stop${union?.solo ? " is-solo" : ""}${!union && !marks.length ? (scholarly === "لا وقف" ? " is-avoid" : " is-scholarly") : ""}`}
                            aria-label={!union && !marks.length && scholarly === "لا وقف" ? `لماذا لا يوقف بعد ${word}` : `تفصيل الوقف بعد ${word}`}
                            aria-pressed={activeStopWpos === index}
                            onClick={() => selectStop(index)}
                          >
                            <span className="waqf-stop-icon" aria-hidden="true">Ⅱ</span>
                            {union?.solo ? (
                              <>
                                <b>انفرد</b>
                                <span>{data.per_reciter[union.reciters[0]]?.name_ar || union.reciters[0]}</span>
                              </>
                            ) : union ? <b>{toArabicDigits(union.count)}/{toArabicDigits(data.reciters_total)}</b> : <b>{marks.length ? "مصحف" : scholarly}</b>}
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
                    موضع وقف (العدد = من وقف من القرّاء)
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block size-[0.8em] rounded-full border-2 border-[var(--wq-solo)] bg-transparent" />
                    انفرد به قارئ واحد
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="inline-block size-[0.8em] rounded-full border border-dashed border-athar-gold bg-transparent" />
                    نصّ عليه إمام أو توجيه فقط
                  </span>
                  {avoidCount ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="inline-block size-[0.8em] rounded-full border border-dashed border-athar-negative bg-transparent" />
                      نهى الأئمة عن الوقف هنا
                    </span>
                  ) : null}
                  <span className="hidden items-center gap-1.5 lg:inline-flex">
                    <kbd className="rounded border border-athar-line px-1 font-athar-ui">[</kbd>
                    <kbd className="rounded border border-athar-line px-1 font-athar-ui">]</kbd>
                    بين المواضع ·
                    <kbd className="rounded border border-athar-line px-1 font-athar-ui">←</kbd>
                    <kbd className="rounded border border-athar-line px-1 font-athar-ui">→</kbd>
                    بين الآيات
                  </span>
                </div>
              </ToolCard>

              <aside className="lg:sticky lg:top-[calc(var(--bar-height)+4.75rem)] lg:max-h-[calc(100dvh-var(--bar-height)-5.75rem)] lg:overflow-y-auto lg:overscroll-contain lg:pb-1">
                <WaqfStopInspector
                  data={data}
                  classical={classical}
                  tawjih={tawjih}
                  wpos={activeStopWpos}
                  stopPositions={stopPositions}
                  playingKey={playingKey}
                  onSelectStop={selectStop}
                  onPlayStop={playReciterStop}
                  onShowAllTawjih={() => showPanel("tawjih")}
                />
              </aside>
            </div>

            <section id="waqf-ayah-panels" className="grid scroll-mt-4 gap-3 md:scroll-mt-[calc(var(--bar-height)+5.5rem)]" aria-label="دراسة الآية كاملة">
              <h2 className="m-0 font-athar-display text-[1.15rem] text-athar-ink">الآية كاملة</h2>
              <div
                className="flex gap-1 overflow-x-auto rounded-xl border border-athar-line bg-athar-canvas-strong p-1 [scrollbar-width:none]"
                role="tablist"
                aria-label="أدوات دراسة الآية"
              >
                {ayahPanels.filter((item) => item.key !== "tawjih" || tawjih?.entries.length).map((item) => {
                  const active = panel === item.key;
                  const count = item.key === "classical" ? classical?.count : item.key === "tawjih" ? tawjih?.entries.length : undefined;
                  return (
                    <button
                      type="button"
                      role="tab"
                      id={`waqf-tab-${item.key}`}
                      aria-controls="waqf-tab-panel"
                      aria-selected={active}
                      key={item.key}
                      onClick={() => setPanel(item.key)}
                      className={cn(
                        "inline-flex min-h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-[9px] px-3.5 text-sm font-semibold whitespace-nowrap text-athar-ink-soft transition-colors hover:text-athar-ink focus-visible:outline-2 focus-visible:outline-athar-accent",
                        active && "bg-athar-surface text-athar-accent shadow-sm hover:text-athar-accent",
                      )}
                    >
                      {item.label}
                      {count ? <span className="rounded-full bg-athar-accent/10 px-1.5 text-[0.7rem] font-bold text-athar-accent">{toArabicDigits(count)}</span> : null}
                    </button>
                  );
                })}
              </div>
              <div id="waqf-tab-panel" role="tabpanel" aria-labelledby={`waqf-tab-${panel}`}>
                {panel === "breath" ? (
                  <ToolCard aria-labelledby="waqf-breath-title">
                    <ToolCardHead title="ترشيح القراءة حسب نَفَسك" titleId="waqf-breath-title">
                      <SegmentedControl
                        variant="pills"
                        label="سعة النفس"
                        value={breath}
                        options={(Object.keys(breathLabels) as BreathProfile[]).map((profile) => ({
                          value: profile,
                          label: breathLabels[profile],
                        }))}
                        onChange={selectBreath}
                      />
                    </ToolCardHead>

                    {selectedProfile ? (
                      <p className="mb-3 text-[0.86rem] text-athar-ink">
                        الأنسب لسعة نَفَسك: <b className="text-athar-accent">{selectedProfile.name}</b>
                        {" · "}
                        أطول نَفَس {toArabicDigits(selectedProfile.longestWords)} كلمة
                        {" · "}
                        نحو {toArabicDigits(selectedProfile.longestSeconds.toFixed(1))}ث
                        {" · "}
                        {toArabicDigits(selectedProfile.detail.phrases.length)} مقاطع
                        {selectedProfile.detail.qasr_munfasil ? " · قصر المنفصل" : ""}
                      </p>
                    ) : (
                      <p className="mb-3 text-[0.86rem] text-athar-ink">لا يتوفر قارئ بصوت قابل للتشغيل لهذه الآية بعد.</p>
                    )}

                    {profiles.length ? (
                      <Field label="القارئ" className="mb-3 max-w-[280px]">
                        <SelectControl
                          id="wq-reciter-select"
                          aria-label="القارئ المختار"
                          value={selectedProfile?.id || ""}
                          onChange={(event) => {
                            stop();
                            setSelectedReciterId(event.target.value);
                          }}
                        >
                          {profiles.map((profile) => (
                            <option key={profile.id} value={profile.id}>{profile.name}</option>
                          ))}
                        </SelectControl>
                      </Field>
                    ) : null}

                    <div className="waqf-segment-list" aria-label="مقاطع القارئ">
                      {selectedProfile?.detail.phrases.map((phrase, index) => {
                        const key = `phrase:${selectedProfile.id}:${index}`;
                        const active = playingKey === key;
                        return (
                          <button type="button" className={active ? "is-playing" : ""} key={key} onClick={() => playPhrase(index)}>
                            <span className="waqf-segment-number">{toArabicDigits(index + 1)}</span>
                            <span className="waqf-segment-words">{data.words.slice(phrase.first_wpos, phrase.last_wpos + 1).join(" ")}</span>
                            <span className="waqf-segment-time">{active ? "Ⅱ" : "▶"} {toArabicDigits((phrase.end - phrase.start).toFixed(1))}ث</span>
                            {active ? <span className="waqf-segment-progress" style={{"--segment-progress": `${Math.round(progress * 100)}%`} as CSSProperties} /> : null}
                          </button>
                        );
                      })}
                    </div>
                  </ToolCard>
                ) : panel === "matrix" ? (
                  <WaqfMatrix data={data} playingKey={playingKey} onPlayStop={playReciterStop} onSelectStop={selectStop} />
                ) : panel === "classical" ? (
                  <WaqfClassical classical={classical} words={data.words} onSelectWpos={selectStop} />
                ) : panel === "tawjih" ? (
                  <WaqfTawjih tawjih={tawjih} words={data.words} onSelectWpos={selectStop} />
                ) : (
                  <WaqfReciters data={data} playingKey={playingKey} onPlayPhrase={playReciterPhrase} />
                )}
              </div>
            </section>
          </>
        ) : null}
      </ToolStack>
    </div>
  );
}
