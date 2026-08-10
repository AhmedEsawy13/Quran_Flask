"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getJson,
  type MemorizationAudio,
  type Reciter,
  type VerseTiming,
} from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";

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
      <button className="reader-audio-launch" type="button" onClick={() => setExpanded(true)}>
        <span aria-hidden="true">◉</span>
        <span><strong>استمع إلى الآية</strong><small>التوقيت والتكرار حسب القارئ</small></span>
      </button>
    );
  }

  return (
    <section className="reader-audio" aria-label="مشغّل التلاوة">
      <audio
        ref={audioRef}
        src={visibleAudio?.audio_url || undefined}
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
      <div className="reader-audio-topline">
        <div>
          <span className="reader-panel-kicker">التلاوة</span>
          <strong>{visibleAudio?.reciter_name_ar || "اختر القارئ"}</strong>
        </div>
        <button type="button" className="reader-panel-close" onClick={() => {
          audioRef.current?.pause();
          onWordChange(null);
          setExpanded(false);
        }} aria-label="إغلاق مشغّل التلاوة">×</button>
      </div>

      {audioError ? <div className="reader-panel-error" role="alert">{audioError}</div> : null}
      <div className="reader-audio-controls" aria-busy={loading}>
        <button
          type="button"
          className="reader-play"
          onClick={() => void togglePlayback()}
          disabled={!verse || loading}
          aria-label={isPlaying ? "إيقاف التلاوة مؤقتًا" : "تشغيل التلاوة"}
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

      <div className="reader-audio-options">
        <label><span>القارئ</span>
          <select value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
            {reciters.length ? reciters.map((reciter) => (
              <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
            )) : <option>جارٍ تحميل القرّاء…</option>}
          </select>
        </label>
        <label><span>التكرار</span>
          <select value={repeatCount} onChange={(event) => {
            cycleRef.current = 0;
            setRepeatCount(Number(event.target.value) as (typeof repeatOptions)[number]);
          }}>
            {repeatOptions.map((count) => (
              <option key={count} value={count}>{count === 0 ? "مستمر" : `${toArabicDigits(count)}×`}</option>
            ))}
          </select>
        </label>
        <label className="reader-audio-check">
          <input type="checkbox" checked={autoAdvance} onChange={(event) => setAutoAdvance(event.target.checked)} />
          <span>انتقال تلقائي</span>
        </label>
      </div>
    </section>
  );
}
