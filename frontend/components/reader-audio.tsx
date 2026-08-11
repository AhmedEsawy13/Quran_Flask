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
import { Button, Field, IconButton, SelectControl, StatusState, Surface } from "@/components/ui/primitives";

type ReaderAudioProps = {
  surahNumber: number;
  ayahNumber: number;
  onAdvance: () => Promise<void> | void;
  atLastAyah: boolean;
  onWordChange: (wordIndex: number | null) => void;
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
}: ReaderAudioProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const cycleRef = useRef(0);
  const boundaryHandledRef = useRef(false);
  const [expanded, setExpanded] = useState(false);
  const [reciters, setReciters] = useState<Reciter[]>([]);
  const [reciterId, setReciterId] = useState("husary");
  const [audioResult, setAudioResult] = useState<AudioResult>({key: "", data: null, error: ""});
  const [isPlaying, setIsPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [repeatCount, setRepeatCount] = useState<(typeof repeatOptions)[number]>(1);
  const [autoAdvance, setAutoAdvance] = useState(false);
  const audioKey = `${surahNumber}:${reciterId}`;
  const visibleAudio = audioResult.key === audioKey ? audioResult.data : null;
  const audioError = audioResult.key === audioKey ? audioResult.error : "";
  const loading = expanded && audioResult.key !== audioKey;
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
    if (!expanded) return;
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
  }, [expanded, audioKey, surahNumber, reciterId]);

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

  useEffect(() => {
    if (reciters.length) window.localStorage.setItem("athar-reader-reciter", reciterId);
  }, [reciterId, reciters.length]);

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

  if (!expanded) {
    return (
      <Button
        className="mx-auto min-h-0 w-full max-w-[790px] justify-start rounded-athar-md bg-[color-mix(in_srgb,var(--athar-accent)_5%,var(--athar-surface))] p-4 text-start hover:bg-[color-mix(in_srgb,var(--athar-accent)_9%,var(--athar-surface))]"
        onClick={() => setExpanded(true)}
      >
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-athar-accent text-athar-on-accent" aria-hidden="true">◉</span>
        <span className="grid gap-0.5">
          <strong>استمع إلى الآية</strong>
          <small className="font-normal text-athar-ink-faint">التوقيت والتكرار حسب القارئ</small>
        </span>
      </Button>
    );
  }

  return (
    <Surface as="section" className="mx-auto w-full max-w-[790px] rounded-athar-md p-5" aria-label="مشغّل التلاوة">
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
      <div className="flex items-start justify-between gap-5">
        <div className="grid gap-0.5">
          <span className="text-[0.7rem] font-bold text-athar-gold">التلاوة</span>
          <strong className="text-athar-ink">{visibleAudio?.reciter_name_ar || "اختر القارئ"}</strong>
        </div>
        <IconButton label="إغلاق مشغّل التلاوة" className="size-9 text-xl" onClick={() => {
          audioRef.current?.pause();
          onWordChange(null);
          setExpanded(false);
        }}>×</IconButton>
      </div>

      {audioError ? <StatusState tone="error" className="mt-4 justify-center">{audioError}</StatusState> : null}
      <div className="my-5 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-4" aria-busy={loading}>
        <Button
          size="icon"
          variant="primary"
          className="size-[54px] text-base"
          onClick={() => void togglePlayback()}
          disabled={!verse || loading}
          aria-label={isPlaying ? "إيقاف التلاوة مؤقتًا" : "تشغيل التلاوة"}
        >
          {loading ? "…" : isPlaying ? "Ⅱ" : "▶"}
        </Button>
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 text-[0.7rem] tabular-nums text-athar-ink-faint max-[520px]:grid-cols-1">
          <input
            className="w-full accent-athar-accent"
            type="range"
            min="0"
            max={duration || 1}
            step="0.05"
            value={Math.min(elapsed, duration || 1)}
            disabled={!verse}
            aria-label="موضع التلاوة داخل الآية"
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
          <span>{formatTime(elapsed)} / {formatTime(duration)}</span>
        </div>
      </div>

      <div className="grid items-end gap-3 border-t border-athar-line-soft pt-4 sm:grid-cols-[minmax(0,1.4fr)_minmax(105px,.55fr)_auto]">
        <Field label="القارئ">
          <SelectControl value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
            {reciters.length ? reciters.map((reciter) => (
              <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
            )) : <option>جارٍ تحميل القرّاء…</option>}
          </SelectControl>
        </Field>
        <Field label="التكرار">
          <SelectControl value={repeatCount} onChange={(event) => {
            cycleRef.current = 0;
            setRepeatCount(Number(event.target.value) as (typeof repeatOptions)[number]);
          }}>
            {repeatOptions.map((count) => (
              <option key={count} value={count}>{count === 0 ? "مستمر" : `${toArabicDigits(count)}×`}</option>
            ))}
          </SelectControl>
        </Field>
        <label className="flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-athar-line px-3 text-sm text-athar-ink-soft">
          <input className="accent-athar-accent" type="checkbox" checked={autoAdvance} onChange={(event) => setAutoAdvance(event.target.checked)} />
          <span>انتقال تلقائي</span>
        </label>
      </div>
    </Surface>
  );
}
