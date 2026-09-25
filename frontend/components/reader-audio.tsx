"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getJson,
  type MemorizationAudio,
  type Reciter,
  type VerseTiming,
} from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";
import { backendMediaUrl } from "@/lib/paths";
import { Button, CheckControl, Field, PlaybackTimeline, SelectControl, StatusState, Surface } from "@/components/ui/primitives";

type ReaderAudioProps = {
  surahNumber: number;
  ayahNumber: number;
  onAdvance: () => Promise<void> | void;
  atLastAyah: boolean;
  onWordChange: (wordIndex: number | null) => void;
  onReciterChange?: (reciterId: string) => void;
  onClose?: () => void;
};

type AudioResult = {
  key: string;
  data: MemorizationAudio | null;
  error: string;
};

const audioCache = new Map<string, MemorizationAudio>();
const repeatOptions = [1, 2, 3, 5, 0] as const;

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "٠:٠٠";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return toArabicDigits(`${minutes}:${remainder}`);
}

export function ReaderAudio({
  surahNumber,
  ayahNumber,
  onAdvance,
  atLastAyah,
  onWordChange,
  onReciterChange,
  onClose,
}: ReaderAudioProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const cycleRef = useRef(0);
  const boundaryHandledRef = useRef(false);
  const [reciters, setReciters] = useState<Reciter[]>([]);
  const [reciterId, setReciterId] = useState("husary");
  const [audioResult, setAudioResult] = useState<AudioResult>({key: "", data: null, error: ""});
  const [isPlaying, setIsPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [repeatCount, setRepeatCount] = useState<(typeof repeatOptions)[number]>(1);
  const [autoAdvance, setAutoAdvance] = useState(false);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const audioKey = `${surahNumber}:${reciterId}`;
  const visibleAudio = audioResult.key === audioKey ? audioResult.data : null;
  const audioError = audioResult.key === audioKey ? audioResult.error : "";
  const loading = audioResult.key !== audioKey;
  const verse = useMemo(
    () => visibleAudio?.verses.find((item) => item.ayah === ayahNumber) || null,
    [visibleAudio, ayahNumber],
  );
  const duration = verse ? Math.max(0, verse.end - verse.start) : 0;

  const updateActiveWord = useCallback((currentTime: number, timing: VerseTiming | null) => {
    if (!timing) {
      onWordChange(null);
      return;
    }
    const active = timing.words.find(([, start, end]) =>
      currentTime >= start - 0.025 && currentTime < end + 0.025
    );
    onWordChange(active ? active[0] : null);
  }, [onWordChange]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Reciter[]>("/backend-api/memorization-reciters", controller.signal)
      .then((items) => {
        setReciters(items);
        const saved = window.localStorage.getItem("athar-reader-reciter");
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
          error: reason instanceof Error ? reason.message : "تعذّر تحميل التلاوة.",
        });
      });
    return () => controller.abort();
  }, [audioKey, surahNumber, reciterId]);

  const seekToVerseStart = useCallback((timing: VerseTiming | null) => {
    const audio = audioRef.current;
    if (!audio || !timing) return;
    audio.currentTime = timing.start;
    boundaryHandledRef.current = false;
    setElapsed(0);
    onWordChange(null);
  }, [onWordChange]);

  useEffect(() => {
    cycleRef.current = 0;
    onWordChange(null);
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    if (verse) seekToVerseStart(verse);
  }, [verse, seekToVerseStart, onWordChange]);

  // Closing the player must not leave a word lit on the page.
  useEffect(() => () => onWordChange(null), [onWordChange]);

  useEffect(() => {
    if (reciters.length) window.localStorage.setItem("athar-reader-reciter", reciterId);
    onReciterChange?.(reciterId);
  }, [reciterId, reciters.length, onReciterChange]);

  const completeVerse = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !verse || boundaryHandledRef.current) return;
    boundaryHandledRef.current = true;
    const shouldRepeat = repeatCount === 0 || cycleRef.current + 1 < repeatCount;
    if (shouldRepeat) {
      cycleRef.current += 1;
      audio.currentTime = verse.start;
      boundaryHandledRef.current = false;
      setElapsed(0);
      onWordChange(null);
      try {
        await audio.play();
      } catch {
        setIsPlaying(false);
      }
      return;
    }
    audio.pause();
    audio.currentTime = verse.end;
    setElapsed(duration);
    setIsPlaying(false);
    onWordChange(null);
    cycleRef.current = 0;
    if (autoAdvance && !atLastAyah) await onAdvance();
  }, [verse, repeatCount, duration, autoAdvance, atLastAyah, onAdvance, onWordChange]);

  useEffect(() => {
    if (!isPlaying || !verse) return;
    let frame = 0;
    const followPlayback = () => {
      const audio = audioRef.current;
      if (!audio || audio.paused) return;
      const current = audio.currentTime;
      updateActiveWord(current, verse);
      if (current >= verse.end - 0.06 && !boundaryHandledRef.current) {
        void completeVerse();
      }
      frame = window.requestAnimationFrame(followPlayback);
    };
    frame = window.requestAnimationFrame(followPlayback);
    return () => window.cancelAnimationFrame(frame);
  }, [isPlaying, verse, updateActiveWord, completeVerse]);

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !verse) return;
    if (!audio.paused) {
      audio.pause();
      setIsPlaying(false);
      return;
    }
    if (audio.currentTime < verse.start || audio.currentTime >= verse.end - 0.05) {
      audio.currentTime = verse.start;
      boundaryHandledRef.current = false;
      setElapsed(0);
      cycleRef.current = 0;
    }
    try {
      await audio.play();
      setIsPlaying(true);
    } catch {
      setIsPlaying(false);
    }
  }, [verse]);

  return (
    <Surface
      as="section"
      id="reader-audio"
      className="mx-auto w-full max-w-[900px] rounded-athar-md p-2.5 shadow-athar-lg sm:p-3"
      aria-label="مشغّل التلاوة"
    >
      <audio
        ref={audioRef}
        src={backendMediaUrl(visibleAudio?.audio_url)}
        preload="metadata"
        onLoadedMetadata={() => seekToVerseStart(verse)}
        onPause={() => setIsPlaying(false)}
        onPlay={() => setIsPlaying(true)}
        onTimeUpdate={(event) => {
          if (!verse) return;
          const current = event.currentTarget.currentTime;
          setElapsed(Math.max(0, Math.min(duration, current - verse.start)));
          updateActiveWord(current, verse);
          if (current >= verse.end - 0.06 && !boundaryHandledRef.current) void completeVerse();
        }}
      />
      {audioError ? <StatusState tone="error" className="mb-2.5 justify-center">{audioError}</StatusState> : null}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5 lg:flex-nowrap" aria-busy={loading}>
        <Button
          size="icon"
          variant="primary"
          className="size-11 shrink-0"
          onClick={() => void togglePlayback()}
          disabled={!verse || loading}
          aria-label={isPlaying ? "إيقاف التلاوة مؤقتًا" : "تشغيل التلاوة"}
        >
          {loading ? (
            <span className="size-4 animate-spin rounded-full border-2 border-current border-e-transparent" aria-hidden="true" />
          ) : (
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5 fill-current">
              {isPlaying ? <path d="M7 5h3.5v14H7zM13.5 5H17v14h-3.5z" /> : <path d="M8 5.5v13L18.5 12z" />}
            </svg>
          )}
        </Button>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="truncate text-[0.72rem] font-semibold text-athar-ink-soft">
            {visibleAudio?.reciter_name_ar || reciters.find((reciter) => reciter.id === reciterId)?.name_ar || "التلاوة"}
            <span className="text-athar-ink-faint"> · الآية {toArabicDigits(ayahNumber)}</span>
            {repeatCount !== 1 ? <span className="text-athar-accent"> · {repeatCount === 0 ? "تكرار مستمر" : `${toArabicDigits(repeatCount)}×`}</span> : null}
          </span>
          <PlaybackTimeline
            min="0"
            max={duration || 1}
            step="0.05"
            value={Math.min(elapsed, duration || 1)}
            disabled={!verse}
            label="موضع التلاوة داخل الآية"
            className="max-[520px]:grid-cols-[minmax(0,1fr)_auto]"
            time={<>{formatTime(elapsed)} / {formatTime(duration)}</>}
            onChange={(event) => {
              const nextElapsed = Number(event.target.value);
              setElapsed(nextElapsed);
              if (audioRef.current && verse) {
                const current = verse.start + nextElapsed;
                audioRef.current.currentTime = current;
                updateActiveWord(current, verse);
              }
            }}
          />
        </div>
        <Button
          size="icon"
          variant={optionsOpen ? "quiet" : "ghost"}
          className="size-9 shrink-0 lg:hidden"
          aria-label="خيارات التلاوة"
          aria-expanded={optionsOpen}
          aria-controls="reader-audio-options"
          onClick={() => setOptionsOpen((current) => !current)}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[17px] fill-none stroke-current stroke-[1.8] [stroke-linecap:round]">
            <path d="M4 7h10M18 7h2M4 17h2M10 17h10" /><circle cx="16" cy="7" r="2.2" /><circle cx="8" cy="17" r="2.2" />
          </svg>
        </Button>
        {onClose ? (
          <Button size="icon" variant="ghost" className="size-9 shrink-0 lg:order-last" aria-label="إغلاق مشغّل التلاوة" onClick={onClose}>
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4 fill-none stroke-current stroke-2 [stroke-linecap:round]"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </Button>
        ) : null}
        <div
          id="reader-audio-options"
          className={`${optionsOpen ? "grid" : "hidden"} w-full grid-cols-2 items-end gap-2 border-t border-athar-line-soft pt-2.5 lg:grid lg:w-auto lg:shrink-0 lg:grid-cols-[minmax(170px,1fr)_minmax(92px,auto)_auto] lg:border-0 lg:pt-0`}
        >
          <Field label="القارئ" className="col-span-2 lg:col-span-1">
            <SelectControl className="min-h-9 py-1.5" value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
              {reciters.length ? reciters.map((reciter) => (
                <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
              )) : <option>جارٍ تحميل القرّاء…</option>}
            </SelectControl>
          </Field>
          <Field label="التكرار">
            <SelectControl className="min-h-9 py-1.5" value={repeatCount} onChange={(event) => {
              cycleRef.current = 0;
              setRepeatCount(Number(event.target.value) as (typeof repeatOptions)[number]);
            }}>
              {repeatOptions.map((count) => (
                <option key={count} value={count}>{count === 0 ? "مستمر" : `${toArabicDigits(count)}×`}</option>
              ))}
            </SelectControl>
          </Field>
          <CheckControl className="min-h-9" label="انتقال تلقائي" checked={autoAdvance} onChange={(event) => setAutoAdvance(event.target.checked)} />
        </div>
      </div>
    </Surface>
  );
}
