"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useSearchParams } from "next/navigation";
import {
  getJson,
  type ClassicalWaqfPayload,
  type Surah,
  type WaqfPayload,
  type WaqfReciterDetail,
} from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { useBoundedAudio } from "@/lib/use-bounded-audio";
import {
  Button,
  Field,
  HandoffSurface,
  SectionHeader,
  SegmentedControl,
  SelectControl,
  StatTile,
  StatusState,
  Surface,
} from "@/components/ui/primitives";

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

const markLabels: Record<string, string> = {
  "م": "وقف لازم",
  "لا": "لا وقف",
  "ق": "الوقف أولى",
  "ص": "الوصل أولى",
  "ج": "وقف جائز",
  "ع": "وقف المعانقة",
  "س": "سكتة",
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

function markTone(symbol: string) {
  if (symbol === "م" || symbol === "ق") return "strong";
  if (symbol === "لا") return "avoid";
  return "neutral";
}

export function WaqfWorkspace() {
  const searchParams = useSearchParams();
  const initialSurah = Math.min(114, positiveInteger(searchParams.get("surah"), 2));
  const initialAyah = positiveInteger(searchParams.get("ayah"), 255);
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
        setSelectedStopWpos(strongest?.wpos ?? waqf.mushafs[0]?.marks[0]?.wpos ?? null);
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
  }, [surahNumber, ayahNumber, retryToken, requestKey, stop]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("ayah", String(ayahNumber));
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [surahNumber, ayahNumber]);

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

  const retry = () => {
    setCatalogError("");
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  };

  return (
    <section className="grid gap-4 sm:gap-[18px]" aria-label="مساحة مُكْث لدراسة الوقف">
      <audio ref={audioRef} preload="metadata" className="hidden" />

      <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 border-y border-athar-line-soft py-2.5 text-xs" aria-label="محاور مُكْث">
        <span className="font-bold text-athar-gold">اقرأ الدليل</span>
        <a className="text-athar-ink-soft underline-offset-4 hover:text-athar-accent hover:underline" href="#waqf-verse-title">موضع الوقف</a>
        <a className="text-athar-ink-soft underline-offset-4 hover:text-athar-accent hover:underline" href="#waqf-breath-title">قراءة النَّفَس</a>
        <a className="text-athar-ink-soft underline-offset-4 hover:text-athar-accent hover:underline" href="#waqf-comparison-title">قارن الشهادات</a>
        <a className="ms-auto font-bold text-athar-accent underline-offset-4 hover:underline" href={legacyUrl(`/waqf-lab?surah=${surahNumber}&ayah=${ayahNumber}`)}>مختبر الوقف ↗</a>
      </nav>

      <Surface
        variant="toolbar"
        className="grid grid-cols-[minmax(0,1fr)_minmax(92px,.55fr)] items-end gap-2 rounded-athar-md p-3 md:sticky md:top-[calc(var(--bar-height)+.5rem)] md:z-20 md:grid-cols-[minmax(180px,1fr)_minmax(110px,.45fr)_auto] lg:gap-3 lg:p-3.5"
      >
        <Field label="السورة">
          <SelectControl value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>)}
          </SelectControl>
        </Field>
        <Field label="الآية">
          <SelectControl value={ayahNumber} onChange={(event) => { stop(); setAyahNumber(Number(event.target.value)); }} disabled={!ayahNumbers.length}>
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </SelectControl>
        </Field>
        <div className="col-span-2 flex gap-2 md:col-span-1">
          <Button className="flex-1" variant="quiet" onClick={() => setAyahNumber((value) => value - 1)} disabled={ayahNumber <= 1}>السابقة</Button>
          <Button className="flex-1" onClick={() => setAyahNumber((value) => value + 1)} disabled={!ayahNumbers.length || ayahNumber >= ayahNumbers.length}>التالية</Button>
        </div>
      </Surface>

      {catalogError || visible?.error ? (
        <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
          {catalogError || visible?.error}
        </StatusState>
      ) : null}

      {!visible ? <StatusState tone="loading" className="min-h-24 justify-center">جارٍ تحميل دليل الوقف…</StatusState> : null}

      {data ? (
        <>
          <Surface as="section" className="scroll-mt-[calc(var(--bar-height)+1rem)] rounded-athar-lg p-4 sm:p-5 md:scroll-mt-[calc(var(--bar-height)+7rem)] md:p-6" aria-labelledby="waqf-verse-title">
            <SectionHeader
              eyebrow="الشهادة الأولى · موضع الوقف"
              id="waqf-verse-title"
              title={`سورة ${selectedSurah?.name || ""} · الآية ${toArabicDigits(ayahNumber)}`}
              description={`${toArabicDigits(data.reciters_total)} قارئًا · ${toArabicDigits(data.union_stops.length)} موضعًا · نحو ${toArabicDigits(Math.round(data.full_duration || 0))}ث`}
              className="mb-4"
            />

            <div className="mb-4 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:thin]" aria-label="أقوى مواضع الوقف">
              {[...data.union_stops]
                .filter((stopItem) => stopItem.wpos < data.words.length - 1)
                .sort((a, b) => b.count - a.count || a.wpos - b.wpos)
                .slice(0, 5)
                .map((stopItem) => (
                  <Button
                    size="sm"
                    variant="quiet"
                    className="rounded-full border-athar-gold/25 bg-athar-gold/5"
                    key={stopItem.wpos}
                    onClick={() => setSelectedStopWpos(stopItem.wpos)}
                  >
                    <span>{data.words[stopItem.wpos]}</span>
                    <strong className="text-athar-gold">{toArabicDigits(stopItem.count)}/{toArabicDigits(data.reciters_total)}</strong>
                  </Button>
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
                        {marks.slice(0, 2).map((mark, markIndex) => (
                          <span className={`waqf-symbol is-${markTone(mark.symbol)}`} key={`${mark.mushaf}-${markIndex}`}>{mark.symbol}</span>
                        ))}
                        {union ? <small>{toArabicDigits(union.count)}/{toArabicDigits(data.reciters_total)}</small> : null}
                      </button>
                    ) : null}
                  </span>
                );
              })}
            </div>

            {selectedStopWpos !== null ? (
              <div className="mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-athar-gold/20 bg-athar-gold/5 px-3 py-2.5 text-xs text-athar-ink-soft">
                <span>الموضع المحدد بعد</span>
                <strong className="font-athar-quran text-xl text-athar-ink">{data.words[selectedStopWpos]}</strong>
                <span className="text-athar-ink-faint">
                  {selectedUnion ? `${toArabicDigits(selectedUnion.count)} من ${toArabicDigits(data.reciters_total)} قرّاء` : "علامة مصحف"}
                  {selectedMarks.length ? ` · ${toArabicDigits(selectedMarks.length)} علامة` : ""}
                </span>
                <a className="ms-auto font-bold text-athar-accent underline-offset-4 hover:underline" href="#waqf-comparison-title">قارن الشهادات ↓</a>
              </div>
            ) : null}
          </Surface>

          <Surface as="section" className="scroll-mt-[calc(var(--bar-height)+1rem)] rounded-athar-lg p-4 sm:p-5 md:scroll-mt-[calc(var(--bar-height)+7rem)] md:p-6" aria-labelledby="waqf-breath-title">
            <SectionHeader
              eyebrow="الشهادة الثانية · أداء القارئ"
              id="waqf-breath-title"
              title="قراءة تناسب نَفَسك"
              action={
                <SegmentedControl
                  label="سعة النفس"
                  value={breath}
                  options={(Object.keys(breathLabels) as BreathProfile[]).map((profile) => ({value: profile, label: breathLabels[profile]}))}
                  onChange={selectBreath}
                  className="min-w-[250px] rounded-full"
                />
              }
            />

            <Surface variant="subtle" className="mb-5 grid items-end gap-3 rounded-athar-md p-4 sm:grid-cols-[minmax(190px,.75fr)_minmax(0,1.5fr)]">
              <Field label="القارئ">
                <SelectControl aria-label="القارئ المختار" value={selectedProfile?.id || ""} onChange={(event) => { stop(); setSelectedReciterId(event.target.value); }}>
                  {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
                </SelectControl>
              </Field>
              {selectedProfile ? (
                <div className="grid gap-2 sm:grid-cols-2">
                  <StatTile label="أطول نَفَس" value={`${toArabicDigits(selectedProfile.longestWords)} كلمة`} className="bg-athar-surface" />
                  <StatTile label="زمن ومقاطع القراءة" value={`نحو ${toArabicDigits(selectedProfile.longestSeconds.toFixed(1))}ث · ${toArabicDigits(selectedProfile.detail.phrases.length)} مقاطع`} className="bg-athar-surface" />
                  {selectedProfile.detail.qasr_munfasil ? <span className="sm:col-span-2 w-fit rounded-full bg-athar-gold/10 px-3 py-1 text-[0.7rem] font-bold text-athar-gold">قصر المنفصل</span> : null}
                </div>
              ) : null}
            </Surface>

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
          </Surface>

          <Surface as="section" className="scroll-mt-[calc(var(--bar-height)+1rem)] rounded-athar-lg p-4 sm:p-5 md:scroll-mt-[calc(var(--bar-height)+7rem)] md:p-6" aria-labelledby="waqf-comparison-title">
            <SectionHeader
              eyebrow="الشهادة الثالثة · المصحف والإمام"
              id="waqf-comparison-title"
              title="قارن الدليل عند كل موضع"
              description="اختر موضعًا لعرض علامة المصحف، ووقف القرّاء، وقول الإمام."
            />

            <div className="flex gap-2 overflow-x-auto pb-3 [scrollbar-width:thin]" role="tablist" aria-label="مواضع المقارنة">
              {stopPositions.map((wpos) => {
                const union = unionByWpos.get(wpos);
                return (
                  <Button
                    size="sm"
                    variant={selectedStopWpos === wpos ? "primary" : "secondary"}
                    className="grid min-w-[92px] flex-none gap-0.5"
                    role="tab"
                    aria-selected={selectedStopWpos === wpos}
                    key={wpos}
                    onClick={() => setSelectedStopWpos(wpos)}
                  >
                    <span>{data.words[wpos]}</span>
                    <small className="text-[0.65rem] opacity-70">{union ? `${toArabicDigits(union.count)}/${toArabicDigits(data.reciters_total)}` : "مصحف"}</small>
                  </Button>
                );
              })}
            </div>

            {selectedStopWpos !== null ? (
              <Surface variant="subtle" className="rounded-athar-md p-4 sm:p-5" role="tabpanel">
                <div className="mb-4 flex items-center gap-2 text-athar-ink-faint">
                  <span>بعد كلمة</span>
                  <strong className="font-athar-quran text-2xl text-athar-ink">{data.words[selectedStopWpos]}</strong>
                  {selectedUnion?.solo ? <em className="rounded-full bg-athar-gold/10 px-2 py-0.5 text-[0.7rem] not-italic text-athar-gold">انفراد قارئ</em> : null}
                </div>

                <div className="grid gap-3 lg:grid-cols-3">
                  <article className="min-w-0 rounded-xl border border-athar-line-soft bg-athar-surface p-4">
                    <h3 className="mb-3 mt-0 font-athar-display text-xl">علامات المصاحف</h3>
                    {selectedMarks.length ? selectedMarks.map((mark, index) => (
                      <div className="waqf-mark-row" key={`${mark.mushaf}-${index}`}>
                        <span>{mark.mushaf}</span>
                        <strong className={`is-${markTone(mark.symbol)}`}>{mark.symbol}</strong>
                        <small>{markLabels[mark.symbol] || "علامة وقف"}</small>
                      </div>
                    )) : <StatusState className="justify-center">لا تحمل المصاحف المقارنة علامةً هنا.</StatusState>}
                  </article>

                  <article className="min-w-0 rounded-xl border border-athar-line-soft bg-athar-surface p-4">
                    <h3 className="mb-3 mt-0 font-athar-display text-xl">وقوف القرّاء</h3>
                    {selectedUnion?.reciters.length ? selectedUnion.reciters.map((reciterId) => {
                      const detail = data.per_reciter[reciterId];
                      const stopItem = detail?.stops.find((item) => item.wpos === selectedStopWpos);
                      const key = `stop:${reciterId}:${selectedStopWpos}`;
                      return (
                        <button type="button" className={`waqf-reciter-stop${playingKey === key ? " is-playing" : ""}`} key={reciterId} onClick={() => playReciterStop(reciterId, selectedStopWpos)} disabled={!isNativeAudio(detail?.audio_url || null)}>
                          <span>{detail?.name_ar || reciterId}</span>
                          <small>{playingKey === key ? "إيقاف" : `استمع · ${toArabicDigits(stopItem?.time.toFixed(1) || 0)}ث`}</small>
                        </button>
                      );
                    }) : <StatusState className="justify-center">لم يقف قارئ مسجّل في هذا الموضع.</StatusState>}
                  </article>

                  <article className="min-w-0 rounded-xl border border-athar-line-soft bg-athar-surface p-4">
                    <h3 className="mb-3 mt-0 font-athar-display text-xl">قول الإمام</h3>
                    {selectedClassical.length ? selectedClassical.map((entry, index) => {
                      const source = classical?.sources[entry.source];
                      return (
                        <div className="waqf-classical-row" key={`${entry.source}-${index}`}>
                          <div><strong>{entry.grade_raw || entry.grade}</strong><span>{source?.name || entry.source}</span></div>
                          <blockquote>{entry.quote}</blockquote>
                          {entry.note ? <details><summary>العلّة</summary><p>{entry.note}</p></details> : null}
                        </div>
                      );
                    }) : <StatusState className="justify-center">لا يتوفر حكم تراثي موثّق لهذا الموضع بعد.</StatusState>}
                  </article>
                </div>
              </Surface>
            ) : null}
          </Surface>

          <HandoffSurface action={
            <>
              <a href={legacyUrl(`/waqf-lab?surah=${surahNumber}&ayah=${ayahNumber}`)}>مختبر الوقف</a>
              <a href={legacyUrl(`/waqf-practice?surah=${surahNumber}&ayah=${ayahNumber}`)}>تدرّب على الموضع</a>
            </>
          }>
            التحليل القرآني الشامل وتحرير العلامات ما زالا في أدوات Flask المتخصصة.
          </HandoffSurface>
        </>
      ) : null}
    </section>
  );
}
