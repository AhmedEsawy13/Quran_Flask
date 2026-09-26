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
  isContiguousAdvance,
  stepPlayedSeconds,
  stepSeekTime,
  stepStopTime,
} from "@/lib/memorize-schedule";
import { cn } from "@/lib/cn";
import { toArabicDigits } from "@/lib/mushaf";
import { backendMediaUrl } from "@/lib/paths";
import {
  Button,
  CheckControl,
  PlaybackTimeline,
  SelectControl,
  StatusState,
} from "@/components/ui/primitives";
import { readStorage, writeStorage } from "@/lib/storage";

type MemorizePlayerProps = {
  surahNumber: number;
  fromAyah: number;
  toAyah: number;
  activeAyah: number;
  onActiveAyahChange: (ayah: number) => void;
  onWordChange: (wordIndex: number | null) => void;
  chromeHost?: HTMLElement | null;
  controlsHost?: HTMLElement | null;
  playbackLocked?: boolean;
  /** Where the one-line session status renders (the strip under the toolbar). */
  statusHost?: HTMLElement | null;
  /** Shown instead of the session status (e.g. while picking a range). */
  statusOverride?: React.ReactNode;
  /** Shown before the session has started. */
  idleStatus?: React.ReactNode;
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
  controlsHost = null,
  playbackLocked = false,
  statusHost = null,
  statusOverride = null,
  idleStatus = null,
}: MemorizePlayerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const seekingRef = useRef(false);
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

  const splitMode = splitAtPauses ? "waqf" : "acoustic";
  const audioKey = `${surahNumber}:${reciterId}:${splitMode}`;
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
  // One timing basis (seek → stop, pads included) for the estimate, «باقٍ», and seeking.
  const playedSeconds = useMemo(() => schedule.map((_, index) => stepPlayedSeconds(schedule, index)), [schedule]);
  const totalDuration = useMemo(() => playedSeconds.reduce((total, seconds) => total + seconds, 0), [playedSeconds]);
  const completedDuration = useMemo(
    () => playedSeconds.slice(0, stepIndex).reduce((total, seconds) => total + seconds, 0),
    [playedSeconds, stepIndex],
  );
  const expectedDuration = totalDuration;
  const remainingDuration = Math.max(0, totalDuration - completedDuration - elapsed);

  const setPlaying = useCallback((playing: boolean) => {
    playingRef.current = playing;
    setIsPlaying(playing);
  }, []);

  useEffect(() => {
    activeAyahRef.current = activeAyah;
  }, [activeAyah]);

  // `force` re-announces an unchanged ayah when a step starts, so a page the
  // reader turned away from follows the recitation back.
  const publishAyah = useCallback((ayah: number, force = false) => {
    if (activeAyahRef.current === ayah && !force) return;
    if (activeAyahRef.current !== ayah) internalAyahRef.current = ayah;
    activeAyahRef.current = ayah;
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

  const goToStep = useCallback(async (nextIndex: number, autoplay: boolean, preserveTime = false) => {
    const audio = audioRef.current;
    if (!audio || !schedule.length) return;
    const boundedIndex = Math.min(schedule.length - 1, Math.max(0, nextIndex));
    const step = schedule[boundedIndex];
    stepIndexRef.current = boundedIndex;
    setStepIndex(boundedIndex);
    boundaryHandledRef.current = false;
    setElapsed(preserveTime ? Math.max(0, audio.currentTime - step.start) : 0);
    publishAyah(step.startAyah, autoplay);
    onWordChange(null);
    if (!preserveTime) {
      seekingRef.current = true;
      try {
        audio.currentTime = stepSeekTime(step);
      } catch {
        seekingRef.current = false;
        return;
      }
    }
    if (!autoplay) {
      seekingRef.current = false;
      return;
    }
    try {
      if (audio.paused) await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    } finally {
      seekingRef.current = false;
    }
  }, [schedule, publishAyah, onWordChange, setPlaying]);

  const completeCurrentStep = useCallback(async () => {
    const audio = audioRef.current;
    const step = schedule[stepIndexRef.current];
    if (!audio || !step || boundaryHandledRef.current) return;
    boundaryHandledRef.current = true;
    const nextIndex = stepIndexRef.current + 1;
    if (nextIndex < schedule.length) {
      await goToStep(nextIndex, true, isContiguousAdvance(step, schedule[nextIndex]));
      return;
    }
    if (loopRange) {
      await goToStep(0, true);
      return;
    }
    audio.pause();
    setElapsed(Math.max(0, step.end - step.start));
    setPlaying(false);
    onWordChange(null);
  }, [schedule, loopRange, goToStep, onWordChange, setPlaying]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Reciter[]>("/backend-api/memorization-reciters", controller.signal)
      .then((items) => {
        setReciters(items);
        const saved = readStorage("athar-memorize-reciter");
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
      `/backend-api/memorization/${surahNumber}?reciter=${encodeURIComponent(reciterId)}&mode=${splitMode}`,
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
  }, [audioKey, surahNumber, reciterId, splitMode]);

  useEffect(() => {
    if (reciters.length) writeStorage("athar-memorize-reciter", reciterId);
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
      if (audio && schedule[0]) audio.currentTime = stepSeekTime(schedule[0]);
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
    const followPlayback = () => {
      const audio = audioRef.current;
      if (!audio || audio.paused) return;
      const currentTime = audio.currentTime;
      setElapsed(Math.max(0, Math.min(duration, currentTime - currentStep.start)));
      updatePlaybackPosition(currentTime);
      if (currentTime >= stepStopTime(currentStep, schedule[stepIndex + 1]) && !boundaryHandledRef.current) {
        void completeCurrentStep();
      }
    };
    const id = window.setInterval(followPlayback, 80);
    return () => window.clearInterval(id);
  }, [isPlaying, currentStep, duration, schedule, stepIndex, updatePlaybackPosition, completeCurrentStep]);

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    const step = schedule[stepIndexRef.current];
    if (!audio || !step || playbackLocked) return;
    if (!audio.paused) {
      audio.pause();
      setPlaying(false);
      return;
    }
    if (audio.currentTime < stepSeekTime(step) || audio.currentTime >= stepStopTime(step, schedule[stepIndexRef.current + 1])) {
      await goToStep(stepIndexRef.current, true);
      return;
    }
    publishAyah(activeAyahRef.current, true);
    try {
      await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    }
  }, [schedule, goToStep, setPlaying, playbackLocked, publishAyah]);

  const resetSession = useCallback(() => {
    const audio = audioRef.current;
    audio?.pause();
    setPlaying(false);
    void goToStep(0, false);
  }, [goToStep, setPlaying]);

  const seekSession = useCallback(async (frac: number) => {
    const audio = audioRef.current;
    if (!audio || !schedule.length || playbackLocked) return;
    // The slider shows time; land on the step that owns that moment.
    const target = Math.max(0, Math.min(0.99999, frac)) * totalDuration;
    let nextIndex = schedule.length - 1;
    let before = 0;
    for (let index = 0; index < schedule.length; index += 1) {
      if (before + playedSeconds[index] > target) {
        nextIndex = index;
        break;
      }
      before += playedSeconds[index];
    }
    const step = schedule[nextIndex];
    const currentTime = Math.min(step.end, stepSeekTime(step) + Math.max(0, target - before));
    stepIndexRef.current = nextIndex;
    setStepIndex(nextIndex);
    boundaryHandledRef.current = false;
    setElapsed(Math.max(0, currentTime - step.start));
    publishAyah(step.startAyah);
    onWordChange(null);
    seekingRef.current = true;
    try {
      audio.currentTime = currentTime;
      await audio.play();
      setPlaying(true);
    } catch {
      setPlaying(false);
    } finally {
      seekingRef.current = false;
    }
    updatePlaybackPosition(currentTime);
  }, [schedule, playedSeconds, totalDuration, playbackLocked, publishAyah, onWordChange, setPlaying, updatePlaybackPosition]);

  const sessionProgress = totalDuration
    ? Math.min(1, (completedDuration + elapsed) / totalDuration)
    : 0;
  const canPlay = Boolean(currentStep) && !loading && !playbackLocked;
  const stepKind = currentStep?.kind === "ayah-link"
    ? "ربط الآيات"
    : currentStep?.kind === "phrase-link"
      ? "ربط المقاطع"
      : currentStep?.kind === "phrase"
        ? "مقطع وقفي"
        : "آية كاملة";
  const sessionStructure = `${splitAtPauses ? "مقاطع وقفية" : "آيات كاملة"}${cumulative ? " + ربط تراكمي" : ""}`;
  const transport = (
    <div className="flex min-w-0 flex-1 items-center justify-end gap-1.5" aria-label="شريط جلسة التثبيت">
      <div className="flex shrink-0 items-center gap-0.5">
        <Button
          size="icon"
          variant="ghost"
          className="size-8 max-sm:hidden"
          onClick={() => void goToStep(stepIndex - 1, isPlaying)}
          disabled={stepIndex <= 0 || playbackLocked}
          aria-label="الخطوة السابقة"
        >
          ‹
        </Button>
        <Button
          size="icon"
          variant="primary"
          className="size-9 text-sm shadow-[0_0_0_4px_color-mix(in_srgb,var(--athar-accent)_14%,transparent)]"
          onClick={() => void togglePlayback()}
          disabled={!canPlay}
          aria-label={isPlaying ? "إيقاف جلسة التثبيت مؤقتًا" : "بدء جلسة التثبيت"}
        >
          {loading ? "…" : isPlaying ? "Ⅱ" : "▶"}
        </Button>
        <Button
          size="icon"
          variant="ghost"
          className="size-8 max-sm:hidden"
          onClick={() => void goToStep(stepIndex + 1, isPlaying)}
          disabled={!schedule.length || stepIndex >= schedule.length - 1 || playbackLocked}
          aria-label="الخطوة التالية"
        >
          ›
        </Button>
      </div>
      <PlaybackTimeline
        className="w-full max-w-72 min-w-24 flex-1 max-md:hidden"
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
      <Button size="icon" variant="ghost" className="size-8 text-base hover:text-athar-negative" aria-label="إيقاف" title="إيقاف" onClick={resetSession} disabled={!schedule.length}>
        ×
      </Button>
    </div>
  );

  const audioElement = (
    <audio
      ref={audioRef}
      src={backendMediaUrl(visibleAudio?.audio_url)}
      preload="metadata"
      playsInline
      onLoadedMetadata={() => {
        const audio = audioRef.current;
        const step = schedule[stepIndexRef.current];
        if (!audio || !step) return;
        const start = stepSeekTime(step);
        const stop = stepStopTime(step, schedule[stepIndexRef.current + 1]);
        if (audio.currentTime >= start && audio.currentTime < stop) return;
        audio.currentTime = start;
      }}
      onPause={() => {
        if (seekingRef.current || audioRef.current?.seeking) return;
        setPlaying(false);
      }}
      onPlay={() => setPlaying(true)}
      onTimeUpdate={(event) => {
        const step = schedule[stepIndexRef.current];
        if (!step) return;
        const currentTime = event.currentTarget.currentTime;
        setElapsed(Math.max(0, Math.min(step.end - step.start, currentTime - step.start)));
        updatePlaybackPosition(currentTime);
        if (currentTime >= stepStopTime(step, schedule[stepIndexRef.current + 1]) && !boundaryHandledRef.current) {
          void completeCurrentStep();
        }
      }}
    />
  );

  const sessionControls = (
    <div className="grid gap-3" aria-label="إعدادات الجلسة">
      <div className="flex flex-wrap items-center gap-1.5 text-[0.68rem] font-semibold text-athar-ink-soft" aria-label="خطة جلسة التثبيت" aria-live="polite">
        <strong className="rounded-full bg-athar-accent px-2.5 py-1 font-extrabold text-athar-on-accent">{schedule.length ? `${toArabicDigits(stepIndex + 1)} من ${toArabicDigits(schedule.length)}` : "—"}</strong>
        <span className="rounded-full border border-athar-line-soft bg-athar-line-soft px-2.5 py-1">{stepKind}</span>
        <span className="rounded-full border border-athar-line-soft bg-athar-line-soft px-2.5 py-1">{sessionStructure}</span>
        <span className="rounded-full border border-athar-line-soft bg-athar-line-soft px-2.5 py-1">{visibleAudio?.reciter_name_ar || "جارٍ تجهيز القارئ…"}</span>
      </div>
      {audioError ? <StatusState tone="error">{audioError}</StatusState> : null}
      <div className="flex min-h-11 items-center justify-between gap-3 rounded-xl border border-athar-line-soft bg-athar-canvas-strong px-3 py-2" aria-label="المدة المتوقعة للجلسة" aria-live="polite">
        <span className="text-[0.7rem] font-semibold text-athar-ink-faint">المدة المتوقعة للجلسة</span>
        <strong className="font-display text-base text-athar-accent">{schedule.length ? formatTime(expectedDuration) : "—"}</strong>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="col-span-2 grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
          <span>القارئ</span>
          <SelectControl className="min-h-10 rounded-xl py-1.5" value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
            {reciters.length ? reciters.map((reciter) => (
              <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
            )) : <option>جارٍ تحميل القرّاء…</option>}
          </SelectControl>
        </label>
        <label className="grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
          <span>تكرار الوحدة</span>
          <SelectControl className="min-h-10 rounded-xl py-1.5" value={unitRepetitions} onChange={(event) => setUnitRepetitions(Number(event.target.value) as (typeof unitRepetitionOptions)[number])}>
            {unitRepetitionOptions.map((count) => <option key={count} value={count}>{toArabicDigits(count)}×</option>)}
          </SelectControl>
        </label>
        <label className="grid gap-1 text-[0.7rem] font-semibold text-athar-ink-faint">
          <span>تكرار الربط</span>
          <SelectControl className="min-h-10 rounded-xl py-1.5" value={linkRepetitions} onChange={(event) => setLinkRepetitions(Number(event.target.value) as (typeof linkRepetitionOptions)[number])} disabled={!cumulative}>
            {linkRepetitionOptions.map((count) => <option key={count} value={count}>{toArabicDigits(count)}×</option>)}
          </SelectControl>
        </label>
        <div className="col-span-2 grid gap-1.5">
          <CheckControl className="min-h-9 rounded-[10px] text-xs" label="ربط تراكمي" checked={cumulative} onChange={(event) => setCumulative(event.target.checked)} />
          <CheckControl className="min-h-9 rounded-[10px] text-xs" label="قسّم حسب الوقف" checked={splitAtPauses} onChange={(event) => setSplitAtPauses(event.target.checked)} />
          <CheckControl className="min-h-9 rounded-[10px] text-xs" label="أعد النطاق" checked={loopRange} onChange={(event) => setLoopRange(event.target.checked)} />
        </div>
      </div>
    </div>
  );

  // Space plays/pauses from anywhere except fields and controls that own the key.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== " " || event.altKey || event.ctrlKey || event.metaKey || event.repeat) return;
      const target = event.target as HTMLElement | null;
      if (target?.isContentEditable || target?.closest("input, select, textarea, button, summary, a, [role='dialog']")) return;
      event.preventDefault();
      void togglePlayback();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [togglePlayback]);

  // Lock-screen / earbud controls on phones.
  useEffect(() => {
    if (typeof navigator === "undefined" || !("mediaSession" in navigator) || !currentStep) return;
    const session = navigator.mediaSession;
    try {
      session.metadata = new MediaMetadata({
        title: currentStep.label,
        artist: visibleAudio?.reciter_name_ar || "",
        album: "تثبيت · أثَر",
      });
      session.setActionHandler("play", () => void togglePlayback());
      session.setActionHandler("pause", () => void togglePlayback());
      session.setActionHandler("previoustrack", () => void goToStep(stepIndexRef.current - 1, playingRef.current));
      session.setActionHandler("nexttrack", () => void goToStep(stepIndexRef.current + 1, playingRef.current));
    } catch {
      // Older browsers lack some actions; the in-page controls still work.
    }
  }, [currentStep, visibleAudio?.reciter_name_ar, togglePlayback, goToStep]);

  const sessionStarted = isPlaying || stepIndex > 0 || elapsed > 0.05;
  const status = statusOverride ? statusOverride : audioError ? (
    <span className="truncate text-athar-negative">تعذّر تحميل تلاوة هذا القارئ للسورة — اختر قارئًا آخر من «القارئ والتكرار».</span>
  ) : sessionStarted && currentStep ? (
    <span className="flex min-w-0 items-center gap-2" aria-label="الخطوة الحالية">
      <span className={cn("size-2 shrink-0 rounded-full", isPlaying ? "animate-pulse bg-athar-accent" : "bg-athar-ink-faint")} aria-hidden="true" />
      <b className="truncate text-athar-ink">{currentStep.label}</b>
      {currentStep.repetitionTotal > 1 ? (
        <span className="flex shrink-0 items-center gap-1" aria-label={`التكرار ${toArabicDigits(currentStep.repetition)} من ${toArabicDigits(currentStep.repetitionTotal)}`}>
          {Array.from({length: currentStep.repetitionTotal}, (_, index) => (
            <span
              key={index}
              className={cn("size-1.5 rounded-full", index < currentStep.repetition ? "bg-athar-accent" : "bg-athar-line")}
            />
          ))}
        </span>
      ) : null}
      <span className="shrink-0 rounded-full bg-athar-accent/10 px-2 py-0.5 text-[0.66rem] font-bold text-athar-accent max-sm:hidden">{stepKind}</span>
      <span className="shrink-0 tabular-nums text-athar-ink-faint">{toArabicDigits(stepIndex + 1)}/{toArabicDigits(schedule.length)}</span>
    </span>
  ) : idleStatus;

  return (
    <>
      {statusHost ? createPortal(
        <>
          {status}
          {sessionStarted && !statusOverride ? (
            <span
              className="absolute inset-x-0 bottom-0 h-0.5 origin-right bg-athar-accent transition-transform duration-300"
              style={{transform: `scaleX(${sessionProgress})`}}
              aria-hidden="true"
            />
          ) : null}
        </>,
        statusHost,
      ) : null}
      <div aria-label="جلسة التكرار" className="absolute size-px overflow-hidden">
        {audioElement}
      </div>
      {chromeHost ? createPortal(transport, chromeHost) : transport}
      {controlsHost ? createPortal(sessionControls, controlsHost) : sessionControls}
    </>
  );
}
