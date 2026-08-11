"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getJson,
  type MemorizationAudio,
  type Reciter,
  type VerseTiming,
} from "@/lib/api";
import {
  buildMemorizationSchedule,
  firstStepForAyah,
} from "@/lib/memorize-schedule";
import { toArabicDigits } from "@/lib/mushaf";
import { backendMediaUrl } from "@/lib/paths";

type MemorizePlayerProps = {
  surahNumber: number;
  fromAyah: number;
  toAyah: number;
  activeAyah: number;
  onActiveAyahChange: (ayah: number) => void;
  onWordChange: (wordIndex: number | null) => void;
};

type AudioResult = {
  key: string;
  data: MemorizationAudio | null;
  error: string;
};

const audioCache = new Map<string, MemorizationAudio>();
const unitRepetitionOptions = [1, 2, 3, 5, 7, 10] as const;
const linkRepetitionOptions = [1, 2, 3] as const;

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "٠:٠٠";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return toArabicDigits(`${minutes}:${remainder}`);
}

function timingAt(verses: VerseTiming[], currentTime: number) {
  return verses.find(
    (verse) => currentTime >= verse.start - 0.025 && currentTime < verse.end + 0.025,
  ) || null;
}

export function MemorizePlayer({
  surahNumber,
  fromAyah,
  toAyah,
  activeAyah,
  onActiveAyahChange,
  onWordChange,
}: MemorizePlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const boundaryHandledRef = useRef(false);
  const stepIndexRef = useRef(0);
  const playingRef = useRef(false);
  const internalAyahRef = useRef<number | null>(null);
  const activeAyahRef = useRef(activeAyah);
  const [reciters, setReciters] = useState<Reciter[]>([]);
  const [reciterId, setReciterId] = useState("husary");
  const [audioResult, setAudioResult] = useState<AudioResult>({key: "", data: null, error: ""});
  const [isPlaying, setIsPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stepIndex, setStepIndex] = useState(0);
  const [unitRepetitions, setUnitRepetitions] = useState<(typeof unitRepetitionOptions)[number]>(3);
  const [linkRepetitions, setLinkRepetitions] = useState<(typeof linkRepetitionOptions)[number]>(1);
  const [cumulative, setCumulative] = useState(true);
  const [splitAtPauses, setSplitAtPauses] = useState(true);
  const [loopRange, setLoopRange] = useState(false);

  const audioKey = `${surahNumber}:${reciterId}`;
  const visibleAudio = audioResult.key === audioKey ? audioResult.data : null;
  const audioError = audioResult.key === audioKey ? audioResult.error : "";
  const loading = audioResult.key !== audioKey;
  const selectedVerses = useMemo(
    () => visibleAudio?.verses.filter((verse) => verse.ayah >= fromAyah && verse.ayah <= toAyah) || [],
    [visibleAudio, fromAyah, toAyah],
  );
  const schedule = useMemo(() => buildMemorizationSchedule(visibleAudio?.verses || [], {
    fromAyah,
    toAyah,
    unitRepetitions,
    linkRepetitions,
    cumulative,
    splitAtPauses,
  }), [visibleAudio, fromAyah, toAyah, unitRepetitions, linkRepetitions, cumulative, splitAtPauses]);
  const currentStep = schedule[stepIndex] || null;
  const duration = currentStep ? Math.max(0, currentStep.end - currentStep.start) : 0;
  const completedDuration = useMemo(
    () => schedule.slice(0, stepIndex).reduce((total, step) => total + Math.max(0, step.end - step.start), 0),
    [schedule, stepIndex],
  );
  const totalDuration = useMemo(
    () => schedule.reduce((total, step) => total + Math.max(0, step.end - step.start), 0),
    [schedule],
  );
  const remainingDuration = Math.max(0, totalDuration - completedDuration - elapsed);

  const setPlaying = useCallback((playing: boolean) => {
    playingRef.current = playing;
    setIsPlaying(playing);
  }, []);

  useEffect(() => {
    activeAyahRef.current = activeAyah;
  }, [activeAyah]);

  const publishAyah = useCallback((ayah: number) => {
    if (activeAyahRef.current === ayah) return;
    activeAyahRef.current = ayah;
    internalAyahRef.current = ayah;
    onActiveAyahChange(ayah);
  }, [onActiveAyahChange]);

  const updatePlaybackPosition = useCallback((currentTime: number) => {
    const verse = timingAt(selectedVerses, currentTime);
    if (!verse) {
      onWordChange(null);
      return;
    }
    publishAyah(verse.ayah);
    const activeWord = verse.words.find(([, start, end]) =>
      currentTime >= start - 0.025 && currentTime < end + 0.025
    );
    onWordChange(activeWord ? activeWord[0] : null);
  }, [selectedVerses, publishAyah, onWordChange]);

  const goToStep = useCallback(async (nextIndex: number, autoplay: boolean) => {
    const audio = audioRef.current;
    if (!audio || !schedule.length) return;
    const boundedIndex = Math.min(schedule.length - 1, Math.max(0, nextIndex));
    const step = schedule[boundedIndex];
    stepIndexRef.current = boundedIndex;
    setStepIndex(boundedIndex);
    boundaryHandledRef.current = false;
    setElapsed(0);
    publishAyah(step.startAyah);
    onWordChange(null);
    try {
      audio.currentTime = step.start;
    } catch {
      return;
    }
    if (!autoplay) return;
    try {
      await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  }, [schedule, publishAyah, onWordChange, setPlaying]);

  const completeCurrentStep = useCallback(async () => {
    const audio = audioRef.current;
    const step = schedule[stepIndexRef.current];
    if (!audio || !step || boundaryHandledRef.current) return;
    boundaryHandledRef.current = true;
    const nextIndex = stepIndexRef.current + 1;
    if (nextIndex < schedule.length) {
      await goToStep(nextIndex, true);
      return;
    }
    if (loopRange) {
      await goToStep(0, true);
      return;
    }
    audio.pause();
    audio.currentTime = step.end;
    setElapsed(Math.max(0, step.end - step.start));
    setPlaying(false);
    onWordChange(null);
  }, [schedule, loopRange, goToStep, onWordChange, setPlaying]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Reciter[]>("/backend-api/memorization-reciters", controller.signal)
      .then((items) => {
        setReciters(items);
        const saved = window.localStorage.getItem("athar-memorize-reciter");
        if (saved && items.some((item) => item.id === saved)) setReciterId(saved);
      })
      .catch(() => setReciters([]));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const cached = audioCache.get(audioKey);
    if (cached) {
      queueMicrotask(() => setAudioResult({key: audioKey, data: cached, error: ""}));
      return;
    }
    const controller = new AbortController();
    getJson<MemorizationAudio>(
      `/backend-api/memorization/${surahNumber}?reciter=${encodeURIComponent(reciterId)}`,
      controller.signal,
    )
      .then((data) => {
        audioCache.set(audioKey, data);
        setAudioResult({key: audioKey, data, error: ""});
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAudioResult({
          key: audioKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل جلسة التثبيت.",
        });
      });
    return () => controller.abort();
  }, [audioKey, surahNumber, reciterId]);

  useEffect(() => {
    if (reciters.length) window.localStorage.setItem("athar-memorize-reciter", reciterId);
  }, [reciterId, reciters.length]);

  useEffect(() => {
    const audio = audioRef.current;
    audio?.pause();
    playingRef.current = false;
    stepIndexRef.current = 0;
    boundaryHandledRef.current = false;
    queueMicrotask(() => {
      setIsPlaying(false);
      setStepIndex(0);
      setElapsed(0);
      onWordChange(null);
      if (audio && schedule[0]) audio.currentTime = schedule[0].start;
    });
  }, [schedule, onWordChange]);

  useEffect(() => {
    if (internalAyahRef.current === activeAyah) {
      internalAyahRef.current = null;
      return;
    }
    if (!schedule.length) return;
    const targetIndex = firstStepForAyah(schedule, activeAyah);
    if (targetIndex === stepIndexRef.current) return;
    void goToStep(targetIndex, playingRef.current);
  }, [activeAyah, schedule, goToStep]);

  useEffect(() => {
    if (!isPlaying || !currentStep) return;
    let frame = 0;
    const followPlayback = () => {
      const audio = audioRef.current;
      if (!audio || audio.paused) return;
      const currentTime = audio.currentTime;
      setElapsed(Math.max(0, Math.min(duration, currentTime - currentStep.start)));
      updatePlaybackPosition(currentTime);
      if (currentTime >= currentStep.end - 0.06 && !boundaryHandledRef.current) {
        void completeCurrentStep();
      }
      frame = window.requestAnimationFrame(followPlayback);
    };
    frame = window.requestAnimationFrame(followPlayback);
    return () => window.cancelAnimationFrame(frame);
  }, [isPlaying, currentStep, duration, updatePlaybackPosition, completeCurrentStep]);

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    const step = schedule[stepIndexRef.current];
    if (!audio || !step) return;
    if (!audio.paused) {
      audio.pause();
      setPlaying(false);
      return;
    }
    if (audio.currentTime < step.start || audio.currentTime >= step.end - 0.05) {
      await goToStep(stepIndexRef.current, true);
      return;
    }
    try {
      await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  }, [schedule, goToStep, setPlaying]);

  const resetSession = useCallback(() => {
    const audio = audioRef.current;
    audio?.pause();
    setPlaying(false);
    void goToStep(0, false);
  }, [goToStep, setPlaying]);

  return (
    <section className="memorize-player" aria-label="جلسة التكرار">
      <audio
        ref={audioRef}
        src={backendMediaUrl(visibleAudio?.audio_url)}
        preload="metadata"
        onLoadedMetadata={() => {
          const step = schedule[stepIndexRef.current];
          if (audioRef.current && step) audioRef.current.currentTime = step.start;
        }}
        onPause={() => setPlaying(false)}
        onPlay={() => setPlaying(true)}
        onTimeUpdate={(event) => {
          const step = schedule[stepIndexRef.current];
          if (!step) return;
          const currentTime = event.currentTarget.currentTime;
          setElapsed(Math.max(0, Math.min(step.end - step.start, currentTime - step.start)));
          updatePlaybackPosition(currentTime);
          if (currentTime >= step.end - 0.06 && !boundaryHandledRef.current) {
            void completeCurrentStep();
          }
        }}
      />

      <header className="memorize-player-head">
        <div>
          <span className="reader-panel-kicker">التكرار التراكمي</span>
          <strong>{visibleAudio?.reciter_name_ar || "جارٍ تجهيز القارئ…"}</strong>
          <small>
            {currentStep?.label || `الآية ${toArabicDigits(activeAyah)}`}
            {currentStep && currentStep.repetitionTotal > 1
              ? ` · ${toArabicDigits(currentStep.repetition)} من ${toArabicDigits(currentStep.repetitionTotal)}`
              : ""}
          </small>
        </div>
        <span className={`memorize-player-state${isPlaying ? " is-live" : ""}`}>
          {loading ? "يُحمّل" : isPlaying ? "يُتلى الآن" : "جاهز"}
        </span>
      </header>

      {audioError ? <div className="reader-panel-error" role="alert">{audioError}</div> : null}

      <div className="memorize-plan" aria-label="خطة جلسة التثبيت" aria-live="polite">
        <div>
          <span>الخطوة</span>
          <strong>{schedule.length ? `${toArabicDigits(stepIndex + 1)} من ${toArabicDigits(schedule.length)}` : "—"}</strong>
        </div>
        <div>
          <span>النمط</span>
          <strong>{currentStep?.kind === "ayah-link" ? "ربط الآيات" : currentStep?.kind === "phrase-link" ? "ربط المقاطع" : currentStep?.kind === "phrase" ? "مقطع وقفي" : "آية كاملة"}</strong>
        </div>
        <div>
          <span>المتبقي التقريبي</span>
          <strong>{formatTime(remainingDuration)}</strong>
        </div>
        <div>
          <span>بنية الجلسة</span>
          <strong>
            {splitAtPauses ? "مقاطع وقفية" : "آيات كاملة"}
            {cumulative ? " + ربط تراكمي" : ""}
          </strong>
        </div>
      </div>

      <div className="reader-audio-controls">
        <button
          type="button"
          className="reader-play"
          onClick={() => void togglePlayback()}
          disabled={!currentStep || loading}
          aria-label={isPlaying ? "إيقاف جلسة التثبيت مؤقتًا" : "بدء جلسة التثبيت"}
        >
          {loading ? "…" : isPlaying ? "Ⅱ" : "▶"}
        </button>
        <div className="reader-audio-timeline">
          <input
            type="range"
            min="0"
            max={duration || 1}
            step="0.05"
            value={Math.min(elapsed, duration || 1)}
            disabled={!currentStep}
            aria-label="موضع التلاوة داخل خطوة التثبيت"
            onChange={(event) => {
              const nextElapsed = Number(event.target.value);
              setElapsed(nextElapsed);
              if (audioRef.current && currentStep) {
                const currentTime = currentStep.start + nextElapsed;
                audioRef.current.currentTime = currentTime;
                boundaryHandledRef.current = false;
                updatePlaybackPosition(currentTime);
              }
            }}
          />
          <span>{formatTime(elapsed)} / {formatTime(duration)}</span>
        </div>
      </div>

      <div className="memorize-stepper" aria-label="التنقل بين خطوات التثبيت">
        <button type="button" onClick={() => void goToStep(stepIndex - 1, isPlaying)} disabled={stepIndex <= 0}>الخطوة السابقة</button>
        <button type="button" onClick={() => void goToStep(stepIndex + 1, isPlaying)} disabled={!schedule.length || stepIndex >= schedule.length - 1}>الخطوة التالية</button>
      </div>

      <div className="memorize-player-options">
        <label><span>القارئ</span>
          <select value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
            {reciters.length ? reciters.map((reciter) => (
              <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
            )) : <option>جارٍ تحميل القرّاء…</option>}
          </select>
        </label>
        <label><span>تكرار الوحدة</span>
          <select value={unitRepetitions} onChange={(event) => setUnitRepetitions(Number(event.target.value) as (typeof unitRepetitionOptions)[number])}>
            {unitRepetitionOptions.map((count) => <option key={count} value={count}>{toArabicDigits(count)}×</option>)}
          </select>
        </label>
        <label><span>تكرار الربط</span>
          <select value={linkRepetitions} onChange={(event) => setLinkRepetitions(Number(event.target.value) as (typeof linkRepetitionOptions)[number])} disabled={!cumulative}>
            {linkRepetitionOptions.map((count) => <option key={count} value={count}>{toArabicDigits(count)}×</option>)}
          </select>
        </label>
        <label className="reader-audio-check">
          <input type="checkbox" checked={cumulative} onChange={(event) => setCumulative(event.target.checked)} />
          <span>ربط تراكمي</span>
        </label>
        <label className="reader-audio-check">
          <input type="checkbox" checked={splitAtPauses} onChange={(event) => setSplitAtPauses(event.target.checked)} />
          <span>قسّم حسب الوقف</span>
        </label>
        <label className="reader-audio-check">
          <input type="checkbox" checked={loopRange} onChange={(event) => setLoopRange(event.target.checked)} />
          <span>أعد النطاق</span>
        </label>
        <button type="button" className="memorize-reset" onClick={resetSession}>ابدأ النطاق من أوله</button>
      </div>
    </section>
  );
}
