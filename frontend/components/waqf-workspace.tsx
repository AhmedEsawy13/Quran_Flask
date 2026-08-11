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
    <section className="waqf-workspace" aria-label="مساحة مُكْث لدراسة الوقف">
      <audio ref={audioRef} preload="metadata" className="waqf-audio" />

      <div className="waqf-toolbar">
        <label><span>السورة</span>
          <select value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>)}
          </select>
        </label>
        <label><span>الآية</span>
          <select value={ayahNumber} onChange={(event) => { stop(); setAyahNumber(Number(event.target.value)); }} disabled={!ayahNumbers.length}>
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </select>
        </label>
        <div className="reader-stepper">
          <button type="button" onClick={() => setAyahNumber((value) => value - 1)} disabled={ayahNumber <= 1}>السابقة</button>
          <button type="button" onClick={() => setAyahNumber((value) => value + 1)} disabled={!ayahNumbers.length || ayahNumber >= ayahNumbers.length}>التالية</button>
        </div>
      </div>

      {catalogError || visible?.error ? (
        <div className="reader-alert" role="alert">
          <span>{catalogError || visible?.error}</span>
          <button type="button" onClick={retry}>أعد المحاولة</button>
        </div>
      ) : null}

      {!visible ? <div className="reader-route-skeleton" aria-label="جارٍ تحميل دليل الوقف" /> : null}

      {data ? (
        <>
          <section className="waqf-verse-card" aria-labelledby="waqf-verse-title">
            <header className="waqf-card-head">
              <div>
                <span className="reader-panel-kicker">الشهادة الأولى · موضع الوقف</span>
                <h2 id="waqf-verse-title">سورة {selectedSurah?.name || ""} · الآية {toArabicDigits(ayahNumber)}</h2>
              </div>
              <p>{toArabicDigits(data.reciters_total)} قارئًا · {toArabicDigits(data.union_stops.length)} موضعًا · نحو {toArabicDigits(Math.round(data.full_duration || 0))}ث</p>
            </header>

            <div className="waqf-best-stops" aria-label="أقوى مواضع الوقف">
              {[...data.union_stops]
                .filter((stopItem) => stopItem.wpos < data.words.length - 1)
                .sort((a, b) => b.count - a.count || a.wpos - b.wpos)
                .slice(0, 5)
                .map((stopItem) => (
                  <button type="button" key={stopItem.wpos} onClick={() => setSelectedStopWpos(stopItem.wpos)}>
                    <span>{data.words[stopItem.wpos]}</span>
                    <strong>{toArabicDigits(stopItem.count)}/{toArabicDigits(data.reciters_total)}</strong>
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
          </section>

          <section className="waqf-breath-card" aria-labelledby="waqf-breath-title">
            <header className="waqf-card-head">
              <div>
                <span className="reader-panel-kicker">الشهادة الثانية · أداء القارئ</span>
                <h2 id="waqf-breath-title">قراءة تناسب نَفَسك</h2>
              </div>
              <div className="waqf-breath-picker" aria-label="سعة النفس">
                {(Object.keys(breathLabels) as BreathProfile[]).map((profile) => (
                  <button type="button" key={profile} aria-pressed={breath === profile} onClick={() => selectBreath(profile)}>{breathLabels[profile]}</button>
                ))}
              </div>
            </header>

            <div className="waqf-reciter-row">
              <label><span>القارئ</span>
                <select aria-label="القارئ المختار" value={selectedProfile?.id || ""} onChange={(event) => { stop(); setSelectedReciterId(event.target.value); }}>
                  {profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
                </select>
              </label>
              {selectedProfile ? (
                <p>
                  أطول نَفَس: <strong>{toArabicDigits(selectedProfile.longestWords)} كلمة</strong>
                  <span>نحو {toArabicDigits(selectedProfile.longestSeconds.toFixed(1))}ث · {toArabicDigits(selectedProfile.detail.phrases.length)} مقاطع</span>
                  {selectedProfile.detail.qasr_munfasil ? <em>قصر المنفصل</em> : null}
                </p>
              ) : null}
            </div>

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
          </section>

          <section className="waqf-comparison-card" aria-labelledby="waqf-comparison-title">
            <header className="waqf-card-head">
              <div>
                <span className="reader-panel-kicker">الشهادة الثالثة · المصحف والإمام</span>
                <h2 id="waqf-comparison-title">قارن الدليل عند كل موضع</h2>
              </div>
              <p>اختر موضعًا لعرض علامة المصحف، ووقف القرّاء، وقول الإمام.</p>
            </header>

            <div className="waqf-position-tabs" role="tablist" aria-label="مواضع المقارنة">
              {stopPositions.map((wpos) => {
                const union = unionByWpos.get(wpos);
                return (
                  <button type="button" role="tab" aria-selected={selectedStopWpos === wpos} key={wpos} onClick={() => setSelectedStopWpos(wpos)}>
                    <span>{data.words[wpos]}</span>
                    <small>{union ? `${toArabicDigits(union.count)}/${toArabicDigits(data.reciters_total)}` : "مصحف"}</small>
                  </button>
                );
              })}
            </div>

            {selectedStopWpos !== null ? (
              <div className="waqf-evidence" role="tabpanel">
                <div className="waqf-evidence-title">
                  <span>بعد كلمة</span>
                  <strong>{data.words[selectedStopWpos]}</strong>
                  {selectedUnion?.solo ? <em>انفراد قارئ</em> : null}
                </div>

                <div className="waqf-evidence-grid">
                  <article>
                    <h3>علامات المصاحف</h3>
                    {selectedMarks.length ? selectedMarks.map((mark, index) => (
                      <div className="waqf-mark-row" key={`${mark.mushaf}-${index}`}>
                        <span>{mark.mushaf}</span>
                        <strong className={`is-${markTone(mark.symbol)}`}>{mark.symbol}</strong>
                        <small>{markLabels[mark.symbol] || "علامة وقف"}</small>
                      </div>
                    )) : <p className="reader-empty">لا تحمل المصاحف المقارنة علامةً هنا.</p>}
                  </article>

                  <article>
                    <h3>وقوف القرّاء</h3>
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
                    }) : <p className="reader-empty">لم يقف قارئ مسجّل في هذا الموضع.</p>}
                  </article>

                  <article>
                    <h3>قول الإمام</h3>
                    {selectedClassical.length ? selectedClassical.map((entry, index) => {
                      const source = classical?.sources[entry.source];
                      return (
                        <div className="waqf-classical-row" key={`${entry.source}-${index}`}>
                          <div><strong>{entry.grade_raw || entry.grade}</strong><span>{source?.name || entry.source}</span></div>
                          <blockquote>{entry.quote}</blockquote>
                          {entry.note ? <details><summary>العلّة</summary><p>{entry.note}</p></details> : null}
                        </div>
                      );
                    }) : <p className="reader-empty">لا يتوفر حكم تراثي موثّق لهذا الموضع بعد.</p>}
                  </article>
                </div>
              </div>
            ) : null}
          </section>

          <div className="reader-handoff">
            <span>التحليل القرآني الشامل وتحرير العلامات ما زالا في أدوات Flask المتخصصة.</span>
            <a href={legacyUrl(`/waqf-lab?surah=${surahNumber}&ayah=${ayahNumber}`)}>مختبر الوقف</a>
            <a href={legacyUrl(`/waqf-practice?surah=${surahNumber}&ayah=${ayahNumber}`)}>تدرّب على الموضع</a>
          </div>
        </>
      ) : null}
    </section>
  );
}
