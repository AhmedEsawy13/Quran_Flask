"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
import { ToolCard } from "@/components/tool-chrome";
import {
  Button,
  CheckControl,
  Field,
  PlaybackTimeline,
  ProgressBar,
  SelectControl,
  StatTile,
  StatusState,
} from "@/components/ui/primitives";

type MemorizePlayerProps = {
  surahNumber: number;
  fromAyah: number;
  toAyah: number;
  activeAyah: number;
  onActiveAyahChange: (ayah: number) => void;
  onWordChange: (wordIndex: number | null) => void;
  chromeHost?: HTMLElement | null;
  playbackLocked?: boolean;
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
  chromeHost = null,
  playbackLocked = false,
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
    if (!audio || !step || playbackLocked) return;
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
  }, [schedule, goToStep, setPlaying, playbackLocked]);

  const resetSession = useCallback(() => {
    const audio = audioRef.current;
    audio?.pause();
    setPlaying(false);
    void goToStep(0, false);
  }, [goToStep, setPlaying]);

  const seekSession = useCallback(async (frac: number) => {
    const audio = audioRef.current;
    if (!audio || !schedule.length || playbackLocked) return;
    const bounded = Math.max(0, Math.min(0.99999, frac));
    const nextIndex = Math.min(schedule.length - 1, Math.floor(bounded * schedule.length));
    const within = bounded * schedule.length - nextIndex;
    const step = schedule[nextIndex];
    const currentTime = step.start + within * Math.max(0, step.end - step.start);
    stepIndexRef.current = nextIndex;
    setStepIndex(nextIndex);
    boundaryHandledRef.current = false;
    setElapsed(Math.max(0, currentTime - step.start));
    publishAyah(step.startAyah);
    onWordChange(null);
    try {
      audio.currentTime = currentTime;
      await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
    updatePlaybackPosition(currentTime);
  }, [schedule, playbackLocked, publishAyah, onWordChange, setPlaying, updatePlaybackPosition]);

  const sessionProgress = totalDuration
    ? Math.min(1, (completedDuration + elapsed) / totalDuration)
    : 0;
  const canPlay = Boolean(currentStep) && !loading && !playbackLocked;
  const transport = (
    <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2" aria-label="شريط جلسة التثبيت">
      <Button
        size="icon"
        variant="primary"
        className="size-10 shrink-0 text-sm"
        onClick={() => void togglePlayback()}
        disabled={!canPlay}
        aria-label={isPlaying ? "إيقاف جلسة التثبيت مؤقتًا" : "بدء جلسة التثبيت"}
      >
        {loading ? "…" : isPlaying ? "Ⅱ" : "▶"}
      </Button>
      <PlaybackTimeline
        className="min-w-[12rem] flex-1"
        min="0"
        max={1000}
        step="1"
        value={Math.round(sessionProgress * 1000)}
        disabled={!schedule.length || playbackLocked}
        label="موضع جلسة التثبيت"
        time={<>باقٍ {formatTime(remainingDuration)}</>}
        onChange={(event) => {
          void seekSession(Number(event.target.value) / 1000);
        }}
      />
      <div className="flex gap-1.5" aria-label="التنقل بين خطوات التثبيت">
        <Button
          size="sm"
          variant="quiet"
          onClick={() => void goToStep(stepIndex - 1, isPlaying)}
          disabled={stepIndex <= 0 || playbackLocked}
        >
          الخطوة السابقة
        </Button>
        <Button
          size="sm"
          onClick={() => void goToStep(stepIndex + 1, isPlaying)}
          disabled={!schedule.length || stepIndex >= schedule.length - 1 || playbackLocked}
        >
          الخطوة التالية
        </Button>
        <Button size="sm" variant="quiet" onClick={resetSession} disabled={!schedule.length}>
          إيقاف
        </Button>
      </div>
    </div>
  );

  return (
    <ToolCard aria-label="جلسة التكرار">
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

      <header className="flex items-start justify-between gap-4">
        <div className="grid gap-0.5">
          <span className="text-[0.7rem] font-bold text-athar-gold">التكرار التراكمي</span>
          <strong className="text-athar-ink">{visibleAudio?.reciter_name_ar || "جارٍ تجهيز القارئ…"}</strong>
          <small className="text-athar-ink-faint">
            {currentStep?.label || `الآية ${toArabicDigits(activeAyah)}`}
            {currentStep && currentStep.repetitionTotal > 1
              ? ` · ${toArabicDigits(currentStep.repetition)} من ${toArabicDigits(currentStep.repetitionTotal)}`
              : ""}
          </small>
        </div>
        <span className={`shrink-0 rounded-full px-3 py-1 text-[0.7rem] font-bold ${isPlaying ? "bg-athar-accent/10 text-athar-accent" : "bg-athar-line-soft text-athar-ink-faint"}`}>
          {loading ? "يُحمّل" : isPlaying ? "يُتلى الآن" : "جاهز"}
        </span>
      </header>

      {audioError ? <StatusState tone="error" className="mt-3">{audioError}</StatusState> : null}

      {chromeHost ? createPortal(transport, chromeHost) : (
        <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-3 lg:grid-cols-[auto_minmax(0,1fr)_auto]">
          <Button
            size="icon"
            variant="primary"
            className="size-11 text-sm"
            onClick={() => void togglePlayback()}
            disabled={!canPlay}
            aria-label={isPlaying ? "إيقاف جلسة التثبيت مؤقتًا" : "بدء جلسة التثبيت"}
          >
            {loading ? "…" : isPlaying ? "Ⅱ" : "▶"}
          </Button>
          <PlaybackTimeline
            min="0"
            max={duration || 1}
            step="0.05"
            value={Math.min(elapsed, duration || 1)}
            disabled={!currentStep}
            label="موضع التلاوة داخل خطوة التثبيت"
            time={<>{formatTime(elapsed)} / {formatTime(duration)}</>}
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
          <div className="col-span-2 flex justify-end gap-2 lg:col-span-1" aria-label="التنقل بين خطوات التثبيت">
            <Button size="sm" variant="quiet" onClick={() => void goToStep(stepIndex - 1, isPlaying)} disabled={stepIndex <= 0 || playbackLocked}>الخطوة السابقة</Button>
            <Button size="sm" onClick={() => void goToStep(stepIndex + 1, isPlaying)} disabled={!schedule.length || stepIndex >= schedule.length - 1 || playbackLocked}>الخطوة التالية</Button>
          </div>
        </div>
      )}

      {chromeHost ? (
        <div className="mt-3">
          <PlaybackTimeline
            min="0"
            max={duration || 1}
            step="0.05"
            value={Math.min(elapsed, duration || 1)}
            disabled={!currentStep}
            label="موضع التلاوة داخل خطوة التثبيت"
            time={<>{formatTime(elapsed)} / {formatTime(duration)}</>}
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
        </div>
      ) : null}

      <details className="group mt-3 border-t border-athar-line-soft pt-3">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-bold text-athar-ink marker:content-none [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="text-athar-gold transition-transform group-open:rotate-90">‹</span>
            إعدادات وخطة الجلسة
          </span>
          <small className="font-normal text-athar-ink-faint">
            الخطوة {schedule.length ? `${toArabicDigits(stepIndex + 1)} من ${toArabicDigits(schedule.length)}` : "—"}
          </small>
        </summary>

        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="خطة جلسة التثبيت" aria-live="polite">
          <StatTile label="الخطوة" value={schedule.length ? `${toArabicDigits(stepIndex + 1)} من ${toArabicDigits(schedule.length)}` : "—"} />
          <StatTile label="النمط" value={currentStep?.kind === "ayah-link" ? "ربط الآيات" : currentStep?.kind === "phrase-link" ? "ربط المقاطع" : currentStep?.kind === "phrase" ? "مقطع وقفي" : "آية كاملة"} />
          <StatTile label="المتبقي التقريبي" value={formatTime(remainingDuration)} />
          <StatTile label="بنية الجلسة" value={`${splitAtPauses ? "مقاطع وقفية" : "آيات كاملة"}${cumulative ? " + ربط تراكمي" : ""}`} />
          <ProgressBar className="sm:col-span-2 lg:col-span-4" value={stepIndex + (elapsed > 0 ? Math.min(1, elapsed / Math.max(0.001, duration)) : 0)} max={Math.max(1, schedule.length)} label="تقدّم خطة جلسة التثبيت" />
        </div>

        <div className="mt-4 grid items-end gap-2 border-t border-athar-line-soft pt-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="القارئ" className="sm:col-span-2 lg:col-span-1">
            <SelectControl value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
              {reciters.length ? reciters.map((reciter) => (
                <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
              )) : <option>جارٍ تحميل القرّاء…</option>}
            </SelectControl>
          </Field>
          <Field label="تكرار الوحدة">
            <SelectControl value={unitRepetitions} onChange={(event) => setUnitRepetitions(Number(event.target.value) as (typeof unitRepetitionOptions)[number])}>
              {unitRepetitionOptions.map((count) => <option key={count} value={count}>{toArabicDigits(count)}×</option>)}
            </SelectControl>
          </Field>
          <Field label="تكرار الربط">
            <SelectControl value={linkRepetitions} onChange={(event) => setLinkRepetitions(Number(event.target.value) as (typeof linkRepetitionOptions)[number])} disabled={!cumulative}>
              {linkRepetitionOptions.map((count) => <option key={count} value={count}>{toArabicDigits(count)}×</option>)}
            </SelectControl>
          </Field>
          <CheckControl label="ربط تراكمي" checked={cumulative} onChange={(event) => setCumulative(event.target.checked)} />
          <CheckControl label="قسّم حسب الوقف" checked={splitAtPauses} onChange={(event) => setSplitAtPauses(event.target.checked)} />
          <CheckControl label="أعد النطاق" checked={loopRange} onChange={(event) => setLoopRange(event.target.checked)} />
          <Button className="sm:col-span-2 lg:col-span-3" variant="quiet" onClick={resetSession}>ابدأ النطاق من أوله</Button>
        </div>
      </details>
    </ToolCard>
  );
}
