"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  getJson,
  type ClassicalWaqfPayload,
  type SearchHit,
  type SearchPayload,
  type Surah,
  type WaqfPayload,
  type WaqfReciterDetail,
} from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { useBoundedAudio } from "@/lib/use-bounded-audio";
import { reciterPhrases, waqfMarkGlyph, waqfMarkLabel, waqfMarkTone } from "@/lib/waqf";
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
import { WaqfMatrix } from "@/components/waqf-matrix";
import { WaqfReciters } from "@/components/waqf-reciters";
import { WaqfClassical } from "@/components/waqf-classical";
import { Button, Field, SegmentedControl, SelectControl, StatusState } from "@/components/ui/primitives";
import { introLinkClassName, pillActionClassName } from "@/lib/ui";

type BreathProfile = "short" | "medium" | "long";

type WaqfResult = {
  key: string;
  data: WaqfPayload | null;
  classical: ClassicalWaqfPayload | null;
  error: string;
};

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
  const initialWpos = Number(searchParams.get("wpos"));
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(initialSurah);
  const [ayahNumber, setAyahNumber] = useState(initialAyah);
  const [breath, setBreath] = useState<BreathProfile>("medium");
  const [selectedReciterId, setSelectedReciterId] = useState("");
  const [selectedStopWpos, setSelectedStopWpos] = useState<number | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [catalogError, setCatalogError] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchHits, setSearchHits] = useState<SearchHit[] | null>(null);
  const [searchError, setSearchError] = useState("");
  const [activeHit, setActiveHit] = useState(-1);
  const [result, setResult] = useState<WaqfResult>({key: "", data: null, classical: null, error: ""});
  const {audioRef, playingKey, progress, play, stop} = useBoundedAudio();
  const requestKey = `${surahNumber}:${ayahNumber}:${retryToken}`;
  const visible = result.key === requestKey ? result : null;
  const data = visible?.data || null;
  const classical = visible?.classical || null;
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

  const stopPositions = useMemo(() => {
    const positions = new Set<number>([...unionByWpos.keys(), ...marksByWpos.keys()]);
    return [...positions].sort((a, b) => a - b);
  }, [unionByWpos, marksByWpos]);

  const selectedUnion = selectedStopWpos === null ? null : unionByWpos.get(selectedStopWpos) || null;
  const selectedMarks = selectedStopWpos === null ? [] : marksByWpos.get(selectedStopWpos) || [];
  const selectedClassical = classical?.entries.filter((entry) => entry.wpos === selectedStopWpos) || [];

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
    ])
      .then(([waqf, classicalPayload]) => {
        const nextProfiles = reciterProfiles(waqf);
        const defaultProfile = recommendedProfile(nextProfiles, "medium");
        const strongest = [...waqf.union_stops]
          .filter((stopItem) => stopItem.wpos < waqf.words.length - 1)
          .sort((a, b) => b.count - a.count || a.wpos - b.wpos)[0];
        setResult({key: requestKey, data: waqf, classical: classicalPayload, error: ""});
        setSelectedReciterId((current) => nextProfiles.some((profile) => profile.id === current)
          ? current
          : defaultProfile?.id || "");
        setSelectedStopWpos(
          Number.isInteger(initialWpos) && initialWpos >= 0 && initialWpos < waqf.words.length
            ? initialWpos
            : strongest?.wpos ?? waqf.mushafs[0]?.marks[0]?.wpos ?? null,
        );
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setResult({
          key: requestKey,
          data: null,
          classical: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل دليل الوقف.",
        });
      });
    return () => controller.abort();
  }, [surahNumber, ayahNumber, retryToken, requestKey, stop, initialWpos]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("ayah", String(ayahNumber));
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [surahNumber, ayahNumber]);

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
          previousDisabled={ayahNumber <= 1}
          nextDisabled={!ayahNumbers.length || ayahNumber >= ayahNumbers.length}
          onPrevious={() => setAyahNumber((value) => value - 1)}
          onNext={() => setAyahNumber((value) => value + 1)}
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
                    <span className={`waqf-word-unit${selectedStopWpos === index ? " is-selected" : ""}`} key={`${word}-${index}`}>
                      <span className="waqf-word">{word}</span>
                      {isStop ? (
                        <button
                          type="button"
                          className={`waqf-inline-stop${union?.solo ? " is-solo" : ""}`}
                          aria-label={`تفصيل الوقف بعد ${word}`}
                          onClick={() => setSelectedStopWpos(index)}
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

            <WaqfMatrix
              data={data}
              playingKey={playingKey}
              onPlayStop={playReciterStop}
              onSelectStop={setSelectedStopWpos}
            />

            <ToolCard aria-labelledby="waqf-comparison-title" id="waqf-comparison">
              <ToolCardHead title="قارن الدليل عند كل موضع" titleId="waqf-comparison-title" />
              <p className="-mt-1 mb-3.5 text-[0.88rem] leading-relaxed text-athar-ink-soft">
                اختر موضعًا لعرض علامة المصحف، ووقف القرّاء، وقول الإمام.
                {" "}
                <a className={introLinkClassName()} href="#waqf-comparison-title">قارن الشهادات ↓</a>
              </p>

              <div className="mb-3.5 flex flex-wrap gap-1.5" role="tablist" aria-label="مواضع المقارنة">
                {stopPositions.map((wpos) => {
                  const union = unionByWpos.get(wpos);
                  const selected = selectedStopWpos === wpos;
                  return (
                    <button
                      type="button"
                      className={`inline-flex cursor-pointer flex-col items-start gap-0.5 rounded-[10px] border px-2.5 py-1.5 text-start ${selected ? "border-athar-accent bg-athar-accent/10" : "border-athar-line-soft bg-athar-canvas-strong"}`}
                      role="tab"
                      aria-selected={selected}
                      key={wpos}
                      onClick={() => setSelectedStopWpos(wpos)}
                    >
                      <span className="font-athar-quran text-[1.05rem] leading-snug">{data.words[wpos]}</span>
                      <small className="text-[0.68rem] text-athar-ink-faint">{union ? `${toArabicDigits(union.count)}/${toArabicDigits(data.reciters_total)}` : "مصحف"}</small>
                    </button>
                  );
                })}
              </div>

              {selectedStopWpos !== null ? (
                <div className="grid gap-3.5" role="tabpanel">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2 text-[0.84rem] text-athar-ink-soft">
                    <span>بعد كلمة</span>
                    <strong className="font-athar-quran text-[1.35rem] text-athar-ink">{data.words[selectedStopWpos]}</strong>
                    {selectedUnion?.solo ? (
                      <em className="rounded-full bg-[var(--wq-solo-soft)] px-2 py-0.5 text-[0.68rem] not-italic font-bold text-[var(--wq-solo)]">انفراد قارئ</em>
                    ) : null}
                  </div>

                  <div className="grid gap-3 md:grid-cols-3">
                    <article className="min-w-0 rounded-xl border border-athar-line-soft bg-athar-canvas-strong p-3">
                      <h3 className="mb-2.5 font-athar-display text-[0.92rem] font-bold text-athar-accent">علامات المصاحف</h3>
                      {selectedMarks.length ? selectedMarks.map((mark, index) => (
                        <div className="waqf-mark-row" key={`${mark.mushaf}-${index}`}>
                          <span>{mark.mushaf}</span>
                          <strong className={`is-${waqfMarkTone(mark.symbol)}`}>{waqfMarkGlyph(mark.symbol)}</strong>
                          <small>{waqfMarkLabel(mark.symbol)}</small>
                        </div>
                      )) : <StatusState className="justify-center">لا تحمل المصاحف المقارنة علامةً هنا.</StatusState>}
                    </article>

                    <article className="min-w-0 rounded-xl border border-athar-line-soft bg-athar-canvas-strong p-3">
                      <h3 className="mb-2.5 font-athar-display text-[0.92rem] font-bold text-athar-accent">وقوف القرّاء</h3>
                      {selectedUnion?.reciters.length ? selectedUnion.reciters.map((reciterId) => {
                        const detail = data.per_reciter[reciterId];
                        const stopItem = detail?.stops.find((item) => item.wpos === selectedStopWpos);
                        const key = `stop:${reciterId}:${selectedStopWpos}`;
                        return (
                          <button
                            type="button"
                            className={`waqf-reciter-stop${playingKey === key ? " is-playing" : ""}`}
                            key={reciterId}
                            onClick={() => playReciterStop(reciterId, selectedStopWpos)}
                            disabled={!isNativeAudio(detail?.audio_url || null)}
                          >
                            <span>{detail?.name_ar || reciterId}</span>
                            <small>{playingKey === key ? "إيقاف" : `استمع · ${toArabicDigits(stopItem?.time.toFixed(1) || 0)}ث`}</small>
                          </button>
                        );
                      }) : <StatusState className="justify-center">لم يقف قارئ مسجّل في هذا الموضع.</StatusState>}
                    </article>

                    <article className="min-w-0 rounded-xl border border-athar-line-soft bg-athar-canvas-strong p-3">
                      <h3 className="mb-2.5 font-athar-display text-[0.92rem] font-bold text-athar-accent">قول الإمام</h3>
                      {selectedClassical.length ? selectedClassical.map((entry, index) => {
                        const source = classical?.sources[entry.source];
                        return (
                          <div className="waqf-classical-row" key={`${entry.source}-${index}`}>
                            <div>
                              <strong>{entry.grade_raw || entry.grade}</strong>
                              <span>{source?.name || entry.source}</span>
                            </div>
                            <blockquote>{entry.quote}</blockquote>
                            {entry.note ? <details><summary>العلّة</summary><p>{entry.note}</p></details> : null}
                          </div>
                        );
                      }) : <StatusState className="justify-center">لا يتوفر حكم تراثي موثّق لهذا الموضع بعد.</StatusState>}
                    </article>
                  </div>
                </div>
              ) : null}
            </ToolCard>

            <WaqfClassical classical={classical} words={data.words} />

            <WaqfReciters data={data} playingKey={playingKey} onPlayPhrase={playReciterPhrase} />

            <ToolCard aria-labelledby="wq-lab-cta-title">
              <div className="flex max-w-[42rem] flex-col gap-2">
                <h2 className="m-0 font-athar-display text-[1.1rem] font-bold text-athar-ink" id="wq-lab-cta-title">مختبر الوقف</h2>
                <p className="m-0 text-[0.9rem] leading-relaxed text-athar-ink-soft">بحث بالكلمة، انفرادات القرّاء، واختلاف المصاحف عبر القرآن — خارج دراسة الآية الواحدة.</p>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-3">
                  <a className={pillActionClassName()} href={`/waqf-lab?surah=${surahNumber}&ayah=${ayahNumber}`}>
                    افتح المختبر
                  </a>
                  <a className={introLinkClassName()} href={`/waqf-practice?surah=${surahNumber}&from=${ayahNumber}&to=${ayahNumber}`}>
                    تدرّب على الموضع
                  </a>
                </div>
              </div>
            </ToolCard>
          </>
        ) : null}
      </ToolStack>
    </div>
  );
}
