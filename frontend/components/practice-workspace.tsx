"use client";

import {useCallback, useEffect, useMemo, useRef, useState} from "react";
import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {
  getJson,
  postJson,
  type MushafPage,
  type PracticeGrade,
  type PracticePassage,
  type PracticeVerse,
  type Surah,
} from "@/lib/api";
import {parseAyahRange, toArabicDigits} from "@/lib/mushaf";
import {legacyUrl} from "@/lib/paths";
import {pillActionClassName} from "@/lib/ui";
import {
  DEFAULT_MUSHAF,
  MAX_PRACTICE_SPAN,
  PRACTICE_VERDICTS,
  markCaption,
  orderMushafVersions,
  parseStopKey,
  practiceScoreTitle,
  practiceScoreTone,
  stopCountLabel,
  stopKey,
} from "@/lib/practice";
import {
  ChromeField,
  ChromePill,
  ChromeSelect,
  ToolCard,
  ToolCardHead,
  ToolChrome,
  ToolStack,
} from "@/components/tool-chrome";
import {Button, StatusState} from "@/components/ui/primitives";
import {PracticeMushafPages} from "@/components/practice-mushaf-pages";
import {loadPracticePageRange, practiceUsesApproximateLayout} from "@/lib/practice-pages";

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function PracticeAsrLink({className, children}: {className?: string; children: string}) {
  return (
    <a
      className={className}
      href={legacyUrl("/waqf-practice?surah=2&from=255&to=255")}
      onClick={(event) => {
        event.currentTarget.href = legacyUrl(`/waqf-practice${window.location.search || "?surah=2&from=255&to=255"}`);
      }}
    >
      {children}
    </a>
  );
}

export function PracticeWorkspace() {
  const searchParams = useSearchParams();
  const hasRangeQuery = searchParams.has("surah") || searchParams.has("from") || searchParams.has("ayah") || searchParams.has("to");
  const initialSurah = Math.min(114, positiveInteger(searchParams.get("surah"), 2));
  const initialFrom = positiveInteger(searchParams.get("from"), positiveInteger(searchParams.get("ayah"), 255));
  const initialTo = Math.max(initialFrom, positiveInteger(searchParams.get("to"), initialFrom));
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(initialSurah);
  const [fromAyah, setFromAyah] = useState(initialFrom);
  const [toAyah, setToAyah] = useState(initialTo);
  const [mushafVersions, setMushafVersions] = useState<string[]>([]);
  const [mushaf, setMushaf] = useState(() => searchParams.get("mushaf") || DEFAULT_MUSHAF);
  const [passageResult, setPassageResult] = useState<{key: string; verses: PracticeVerse[]; error: string}>({
    key: "",
    verses: [],
    error: "",
  });
  const [pageResult, setPageResult] = useState<{key: string; pages: MushafPage[]; error: string}>({
    key: "",
    pages: [],
    error: "",
  });
  const [stops, setStops] = useState<Set<string>>(() => new Set());
  const [grade, setGrade] = useState<PracticeGrade | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [gradeError, setGradeError] = useState("");
  const [grading, setGrading] = useState(false);
  const [retryToken, setRetryToken] = useState(0);
  const [sessionReady, setSessionReady] = useState(hasRangeQuery);
  const passageKey = `${surahNumber}:${fromAyah}:${toAyah}:${retryToken}`;
  const verses = useMemo(
    () => (passageResult.key === passageKey ? passageResult.verses : []),
    [passageKey, passageResult.key, passageResult.verses],
  );
  const passageError = passageResult.key === passageKey ? passageResult.error : "";
  const pagesKey = `${passageKey}:${mushaf}`;
  const pages = pageResult.key === pagesKey ? pageResult.pages : [];
  const pageError = pageResult.key === pagesKey ? pageResult.error : "";
  const pagesLoading = !catalogError && pageResult.key !== pagesKey;
  const passageLoading = !catalogError && (passageResult.key !== passageKey || pagesLoading);
  const lastWpos = useMemo(
    () => new Map(verses.map((verse) => [verse.ayah, verse.words.length - 1])),
    [verses],
  );
  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const toOptions = useMemo(
    () => ayahNumbers.filter((number) => number >= fromAyah && number <= fromAyah + MAX_PRACTICE_SPAN),
    [ayahNumbers, fromAyah],
  );

  const loadAyahNumbers = useCallback(async (surah: number, signal?: AbortSignal) => {
    const cached = ayahCache.current.get(surah);
    if (cached) return cached;
    const numbers = await getJson<number[]>(`/backend-api/surahs/${surah}/ayahs`, signal);
    ayahCache.current.set(surah, numbers);
    return numbers;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getJson<Surah[]>("/backend-api/surahs", controller.signal),
      getJson<string[]>("/backend-api/mushaf-versions", controller.signal),
    ])
      .then(([items, versions]) => {
        setSurahs(items);
        const ordered = orderMushafVersions(versions);
        setMushafVersions(ordered);
        setMushaf((current) => (ordered.includes(current) ? current : ordered[0] || DEFAULT_MUSHAF));
        setCatalogError("");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تهيئة بيانات التدريب.");
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
        setFromAyah((from) => {
          const nextFrom = Math.min(Math.max(1, from), last);
          setToAyah((to) => Math.min(Math.max(nextFrom, to), Math.min(last, nextFrom + MAX_PRACTICE_SPAN)));
          return nextFrom;
        });
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
    if (!sessionReady || !ayahNumbers.length || toAyah < fromAyah || toAyah - fromAyah > MAX_PRACTICE_SPAN) return;
    const controller = new AbortController();
    getJson<PracticePassage>(
      `/backend-api/waqf-practice/passage/${surahNumber}/${fromAyah}/${toAyah}`,
      controller.signal,
    )
      .then((payload) => {
        setPassageResult({
          key: passageKey,
          verses: payload.verses || [],
          error: payload.verses?.length ? "" : "لا آيات في هذا المقطع.",
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setPassageResult({
          key: passageKey,
          verses: [],
          error: reason instanceof Error ? reason.message : "تعذّر تحميل المقطع.",
        });
      });
    return () => controller.abort();
  }, [passageKey, sessionReady, surahNumber, fromAyah, toAyah, ayahNumbers.length]);

  useEffect(() => {
    if (!sessionReady || !ayahNumbers.length || toAyah < fromAyah || toAyah - fromAyah > MAX_PRACTICE_SPAN) return;
    const controller = new AbortController();
    loadPracticePageRange(mushaf, surahNumber, fromAyah, toAyah, controller.signal)
      .then((loaded) => setPageResult({key: pagesKey, pages: loaded, error: ""}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setPageResult({
          key: pagesKey,
          pages: [],
          error: reason instanceof Error ? reason.message : "تعذّر تحميل صفحات المصحف.",
        });
      });
    return () => controller.abort();
  }, [ayahNumbers.length, fromAyah, mushaf, pagesKey, sessionReady, surahNumber, toAyah]);

  useEffect(() => {
    if (hasRangeQuery) return;
    const frame = window.requestAnimationFrame(() => {
      const saved = parseAyahRange(window.localStorage.getItem("athar-practice-range"));
      if (saved) {
        setSurahNumber(saved.surah);
        setFromAyah(saved.from);
        setToAyah(Math.min(saved.to, saved.from + MAX_PRACTICE_SPAN));
      }
      setSessionReady(true);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hasRangeQuery]);

  useEffect(() => {
    if (!sessionReady) return;
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("from", String(fromAyah));
    url.searchParams.set("to", String(toAyah));
    url.searchParams.set("mushaf", mushaf);
    url.searchParams.delete("ayah");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    window.localStorage.setItem("athar-practice-range", `${surahNumber}:${fromAyah}:${toAyah}`);
  }, [sessionReady, surahNumber, fromAyah, toAyah, mushaf]);

  const resetAttempt = useCallback(() => {
    setStops(new Set());
    setGrade(null);
    setGradeError("");
  }, []);

  const retry = useCallback(() => {
    setCatalogError("");
    resetAttempt();
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  }, [resetAttempt, surahNumber]);

  const selectSurah = (nextSurah: number) => {
    resetAttempt();
    setSurahNumber(nextSurah);
    setFromAyah(1);
    setToAyah(1);
  };

  const selectFrom = (nextFrom: number) => {
    resetAttempt();
    setFromAyah(nextFrom);
    setToAyah((current) => Math.max(nextFrom, Math.min(current, nextFrom + MAX_PRACTICE_SPAN)));
  };

  const toggleStop = (ayah: number, wpos: number) => {
    const key = stopKey(ayah, wpos);
    setStops((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setGrade(null);
    setGradeError("");
  };

  const clearStops = () => {
    setStops(new Set());
    setGrade(null);
    setGradeError("");
  };

  const gradeStops = async () => {
    if (!stops.size || grading) return;
    const controller = new AbortController();
    setGrading(true);
    setGradeError("");
    try {
      const result = await postJson<PracticeGrade>("/backend-api/waqf-practice/grade", {
        surah: surahNumber,
        from_ayah: fromAyah,
        to_ayah: toAyah,
        mushaf,
        stops: [...stops].map(parseStopKey),
      }, controller.signal);
      setGrade(result);
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setGrade(null);
      setGradeError(reason instanceof Error ? reason.message : "تعذّر تقييم مواضع الوقف.");
    } finally {
      setGrading(false);
    }
  };

  const rangeLabel = selectedSurah
    ? `سورة ${selectedSurah.name} · ${toArabicDigits(fromAyah)}${toAyah > fromAyah ? `–${toArabicDigits(toAyah)}` : ""}`
    : "المقطع";
  const seenVerdicts = useMemo(() => {
    if (!grade) return [];
    const seen = new Set(grade.stops.map((stop) => stop.verdict));
    if (grade.broken_lazim.length) seen.add("error");
    return (Object.keys(PRACTICE_VERDICTS) as PracticeGrade["stops"][number]["verdict"][])
      .filter((verdict) => seen.has(verdict));
  }, [grade]);
  const verdictAt = useMemo(() => {
    const map = new Map<string, PracticeGrade["stops"][number]>();
    grade?.stops.forEach((stop) => map.set(stopKey(stop.ayah, stop.wpos), stop));
    return map;
  }, [grade]);
  const brokenAt = useMemo(() => {
    const map = new Map<string, PracticeGrade["broken_lazim"][number]>();
    grade?.broken_lazim.forEach((item) => map.set(stopKey(item.ayah, item.wpos), item));
    return map;
  }, [grade]);
  const idealAt = useMemo(() => {
    const map = new Map<string, PracticeGrade["ideal"][number]>();
    grade?.ideal.forEach((item) => map.set(stopKey(item.ayah, item.wpos), item));
    return map;
  }, [grade]);

  return (
    <div aria-label="مساحة تدريب الوقف">
      <ToolChrome
        label="إعدادات التدريب"
        pill={(
          <ChromePill role="status" aria-label="ملخص مقطع التدريب">
            {rangeLabel}
          </ChromePill>
        )}
        note="اضغط على كل كلمةٍ وقفتَ عندها، ثم قيّم: النتيجة تعرض هل لكل وقف علامة مصحف وما هي."
      >
        <ChromeField label="السورة">
          <ChromeSelect value={surahNumber} onChange={(event) => selectSurah(Number(event.target.value))} disabled={!surahs.length}>
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => (
              <option key={surah.number} value={surah.number}>{toArabicDigits(surah.number)}. {surah.name}</option>
            ))}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="من آية">
          <ChromeSelect value={fromAyah} onChange={(event) => selectFrom(Number(event.target.value))} disabled={!ayahNumbers.length}>
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="إلى آية">
          <ChromeSelect
            value={toAyah}
            onChange={(event) => {
              resetAttempt();
              setToAyah(Number(event.target.value));
            }}
            disabled={!toOptions.length}
          >
            {toOptions.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </ChromeSelect>
        </ChromeField>
        <ChromeField label="رسم المصحف للتقييم">
          <ChromeSelect value={mushaf} onChange={(event) => { setMushaf(event.target.value); setGrade(null); }} disabled={!mushafVersions.length}>
            {!mushafVersions.length ? <option>جارٍ التحميل…</option> : null}
            {mushafVersions.map((name) => <option key={name} value={name}>{name}</option>)}
          </ChromeSelect>
        </ChromeField>
      </ToolChrome>

      <ToolStack>
        {catalogError ? (
          <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
            {catalogError}
          </StatusState>
        ) : null}

        <ToolCard raised aria-labelledby="wp-passage-title">
          <ToolCardHead title="المقطع" titleId="wp-passage-title" meta={rangeLabel} />
          {passageLoading ? <StatusState tone="loading">جارٍ تحميل المقطع…</StatusState> : null}
          {passageError ? (
            <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
              {passageError}
            </StatusState>
          ) : null}
          {!passageLoading && !passageError && verses.length ? (
            <>
              {pages.length ? (
                <>
                  {practiceUsesApproximateLayout(mushaf) ? (
                    <StatusState className="mb-3">
                      تُعرض علامات مصحف {mushaf} على تخطيط صفحة المدينة للمقارنة؛ التقييم يعتمد علامات المصحف المختار.
                    </StatusState>
                  ) : null}
                  <PracticeMushafPages
                    pages={pages}
                    surahs={surahs}
                    selectedSurah={selectedSurah}
                    surahNumber={surahNumber}
                    fromAyah={fromAyah}
                    toAyah={toAyah}
                    mushaf={mushaf}
                    versesLastWpos={lastWpos}
                    stops={stops}
                    onWordTap={toggleStop}
                    onRetry={retry}
                  />
                </>
              ) : (
                <>
                  {pageError ? (
                    <StatusState
                      tone="error"
                      className="mb-3"
                      action={<Button size="sm" variant="danger" onClick={retry}>أعد تحميل الصفحة</Button>}
                    >
                      {pageError} يمكنك متابعة التدريب بالنص أدناه.
                    </StatusState>
                  ) : null}
                  <div className="practice-passage" dir="rtl">
                    {verses.map((verse) => (
                      <div className="practice-verse" key={verse.ayah}>
                        {verse.words.map((word, index) => {
                          const key = stopKey(verse.ayah, index);
                          const stopped = stops.has(key);
                          const last = index === verse.words.length - 1;
                          return (
                            <span key={key}>
                              <button
                                className={`practice-word${last ? " is-end" : ""}${stopped ? " is-stopped" : ""}`}
                                type="button"
                                aria-pressed={stopped}
                                aria-label={stopped ? `إلغاء الوقف عند ${word}` : `تعليم وقف عند ${word}`}
                                onClick={() => toggleStop(verse.ayah, index)}
                              >
                                {word}
                              </button>
                              {" "}
                            </span>
                          );
                        })}
                        {" "}
                        <span className="practice-ayah-num">{toArabicDigits(verse.ayah)}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
              <footer className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-athar-line pt-4">
                <p className="m-0 text-[0.78rem] text-athar-ink-faint" aria-live="polite">
                  {stopCountLabel(stops.size)}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="ghost" onClick={clearStops} disabled={!stops.size}>مسح</Button>
                  <Button variant="primary" onClick={gradeStops} disabled={!stops.size || grading}>
                    {grading ? "جارٍ التقييم…" : "قيّم وقوفي"}
                  </Button>
                </div>
              </footer>
            </>
          ) : null}
        </ToolCard>

        {gradeError ? (
          <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={gradeStops}>أعد التقييم</Button>}>
            {gradeError}
          </StatusState>
        ) : null}

        {grade ? (
          <ToolCard raised aria-labelledby="wp-result-title">
            <ToolCardHead title="نتيجة التقييم" titleId="wp-result-title" />
            <div className="flex flex-wrap items-center gap-5">
              <div
                className={`practice-score is-${practiceScoreTone(grade.score)}`}
                role="img"
                aria-label={`نتيجة التقييم ${toArabicDigits(grade.score)} بالمئة`}
              >
                <span>{toArabicDigits(grade.score)}</span>
                <small>٪</small>
              </div>
              <div className="grid gap-3">
                <p className="m-0 font-athar-display text-[1.2rem] font-bold text-athar-ink">
                  {practiceScoreTitle(grade.score, grade.summary.errors)}
                </p>
                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full border border-athar-line-soft px-2.5 py-1 text-[0.78rem] text-athar-positive">
                    <b>{toArabicDigits(grade.summary.good)}</b> بعلامة
                  </span>
                  <span className="rounded-full border border-athar-line-soft px-2.5 py-1 text-[0.78rem] text-athar-gold">
                    <b>{toArabicDigits(grade.summary.notes)}</b> بلا علامة
                  </span>
                  <span className="rounded-full border border-athar-line-soft px-2.5 py-1 text-[0.78rem] text-athar-negative">
                    <b>{toArabicDigits(grade.summary.errors)}</b> خطأ
                  </span>
                </div>
              </div>
            </div>

            {seenVerdicts.length ? (
              <div className="mt-4 flex flex-wrap gap-2 border-y border-athar-line py-3">
                {seenVerdicts.map((verdict) => {
                  const meta = PRACTICE_VERDICTS[verdict];
                  return (
                    <span className="inline-flex items-center gap-1.5 text-[0.78rem] text-athar-ink-soft" key={verdict} title={meta.tip}>
                      <span className={`practice-dot is-${meta.cls}`} aria-hidden="true" />
                      {meta.name}
                    </span>
                  );
                })}
              </div>
            ) : null}

            <div className="practice-passage is-graded mt-3" dir="rtl">
              {verses.map((verse) => (
                <div className="practice-verse" key={`graded-${verse.ayah}`}>
                  {verse.words.map((word, index) => {
                    const key = stopKey(verse.ayah, index);
                    const stop = verdictAt.get(key);
                    const broken = brokenAt.get(key);
                    const ideal = idealAt.get(key);
                    let className = "practice-gword";
                    let title = "";
                    let badge = "";
                    let badgeClass = "practice-mark-badge";
                    if (stop) {
                      const meta = PRACTICE_VERDICTS[stop.verdict] || PRACTICE_VERDICTS.unmarked;
                      className += ` is-stop is-${meta.cls}`;
                      title = markCaption(stop);
                      badge = stop.has_mark && stop.mark ? stop.mark : "—";
                      if (!(stop.has_mark && stop.mark)) badgeClass += " is-empty";
                    } else if (broken) {
                      className += " is-missed-lazim";
                      title = `وقف لازم فاتك — علامة المصحف: ${broken.mark || "م"}`;
                      badge = broken.mark || "م";
                    } else if (ideal) {
                      className += " is-ideal";
                      title = `موضع بعلامة ${ideal.mark || ""} (لم تقف عنده)`;
                      badge = ideal.mark || "";
                      badgeClass += " is-ideal";
                    }
                    return (
                      <span key={key}>
                        <span className={className} title={title || undefined}>
                          {word}
                          {badge ? <sup className={badgeClass} aria-label={title}>{badge}</sup> : null}
                        </span>
                        {" "}
                      </span>
                    );
                  })}
                  {" "}
                  <span className="practice-ayah-num">{toArabicDigits(verse.ayah)}</span>
                </div>
              ))}
            </div>

            <div className="mt-4 grid gap-2">
              {grade.broken_lazim.length ? (
                <p className="m-0 rounded-[13px] border border-athar-negative/30 bg-athar-negative/10 px-4 py-3 text-[0.88rem] leading-8 text-athar-ink">
                  <b>وقفٌ لازم فاتك</b> (علامة م):{" "}
                  {grade.broken_lazim.map((item, index) => (
                    <span key={stopKey(item.ayah, item.wpos)}>
                      {index ? "، " : null}
                      <span className="font-athar-quran text-[1.15em]">{item.word}</span>{" "}
                      <small className="text-athar-ink-faint">{toArabicDigits(item.ayah)}</small>
                    </span>
                  ))}
                </p>
              ) : null}
              {grade.ideal.length ? (
                <p className="m-0 rounded-[13px] border border-athar-positive/30 bg-athar-positive/10 px-4 py-3 text-[0.88rem] leading-8 text-athar-ink">
                  <b>علامات مصحف</b> كان يمكنك الوقف عندها:{" "}
                  {grade.ideal.map((item, index) => (
                    <span key={stopKey(item.ayah, item.wpos)}>
                      {index ? "، " : null}
                      <span className="font-athar-quran text-[1.15em]">
                        {item.word}
                        <sup className="practice-mark-badge is-ideal">{item.mark || ""}</sup>
                      </span>{" "}
                      <small className="text-athar-ink-faint">{toArabicDigits(item.ayah)}</small>
                    </span>
                  ))}
                </p>
              ) : null}
              <p className="m-0 rounded-[13px] border border-athar-accent/30 bg-athar-accent/10 px-4 py-3">
                <Link className="inline-flex items-center font-bold text-athar-accent no-underline hover:underline" href={`/waqf?surah=${surahNumber}&ayah=${fromAyah}`}>
                  ادرس هذا الموضع في مُكْث
                </Link>
              </p>
            </div>
          </ToolCard>
        ) : null}

        <ToolCard aria-labelledby="wp-asr-title">
          <div className="flex max-w-[42rem] flex-col gap-2">
            <h2 className="m-0 font-athar-display text-[1.1rem] font-bold text-athar-ink" id="wp-asr-title">التسجيل الصوتي</h2>
            <p className="m-0 text-[0.9rem] leading-relaxed text-athar-ink-soft">
              تعليم الوقف باللمس والتقييم على المطبوع هنا. التسجيل الصوتي وكشف التجويد من التلاوة ما زالا في النسخة السابقة أثناء إكمال النقل.
            </p>
            <a className={pillActionClassName("mt-1.5")} href={legacyUrl(`/waqf-practice?surah=${surahNumber}&from=${fromAyah}&to=${toAyah}`)}>
              افتح التسجيل الصوتي
            </a>
          </div>
        </ToolCard>
      </ToolStack>
    </div>
  );
}
