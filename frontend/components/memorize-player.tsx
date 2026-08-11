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
const repetitionOptions = [1, 3, 5, 10] as const;

function formatTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "٠:٠٠";
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
  return toArabicDigits(`${minutes}:${remainder}`);
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
  const repetitionRef = useRef(0);
  const resumeAfterVerseRef = useRef(false);
  const [reciters, setReciters] = useState<Reciter[]>([]);
  const [reciterId, setReciterId] = useState("husary");
  const [audioResult, setAudioResult] = useState<AudioResult>({key: "", data: null, error: ""});
  const [isPlaying, setIsPlaying] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [repetition, setRepetition] = useState<(typeof repetitionOptions)[number]>(3);
  const [repetitionCycle, setRepetitionCycle] = useState(1);
  const [loopRange, setLoopRange] = useState(false);
  const audioKey = `${surahNumber}:${reciterId}`;
  const visibleAudio = audioResult.key === audioKey ? audioResult.data : null;
  const audioError = audioResult.key === audioKey ? audioResult.error : "";
  const loading = audioResult.key !== audioKey;
  const verse = useMemo(
    () => visibleAudio?.verses.find((item) => item.ayah === activeAyah) || null,
    [visibleAudio, activeAyah],
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

  const seekToVerse = useCallback((timing: VerseTiming | null) => {
    const audio = audioRef.current;
    if (!audio || !timing) return;
    audio.currentTime = timing.start;
    boundaryHandledRef.current = false;
    setElapsed(0);
    onWordChange(null);
  }, [onWordChange]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    setIsPlaying(false);
    seekToVerse(verse);
    const shouldResume = resumeAfterVerseRef.current && Boolean(verse);
    resumeAfterVerseRef.current = false;
    if (!shouldResume) return;
    const frame = window.requestAnimationFrame(() => {
      audio.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    });
    return () => window.cancelAnimationFrame(frame);
  }, [verse, seekToVerse]);

  useEffect(() => {
    const audio = audioRef.current;
    audio?.pause();
    repetitionRef.current = 0;
    queueMicrotask(() => {
      setRepetitionCycle(1);
      setIsPlaying(false);
      onWordChange(null);
    });
  }, [surahNumber, fromAyah, toAyah, reciterId, onWordChange]);

  const completeActiveVerse = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !verse || boundaryHandledRef.current) return;
    boundaryHandledRef.current = true;
    if (repetitionRef.current + 1 < repetition) {
      repetitionRef.current += 1;
      setRepetitionCycle(repetitionRef.current + 1);
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

    repetitionRef.current = 0;
    setRepetitionCycle(1);
    if (activeAyah < toAyah) {
      resumeAfterVerseRef.current = true;
      onActiveAyahChange(activeAyah + 1);
      return;
    }
    if (loopRange) {
      resumeAfterVerseRef.current = true;
      onActiveAyahChange(fromAyah);
      return;
    }
    audio.pause();
    audio.currentTime = verse.end;
    setElapsed(duration);
    setIsPlaying(false);
    onWordChange(null);
  }, [verse, repetition, activeAyah, toAyah, loopRange, fromAyah, duration, onActiveAyahChange, onWordChange]);

  useEffect(() => {
    if (!isPlaying || !verse) return;
    let frame = 0;
    const followPlayback = () => {
      const audio = audioRef.current;
      if (!audio || audio.paused) return;
      const current = audio.currentTime;
      updateActiveWord(current, verse);
      if (current >= verse.end - 0.06 && !boundaryHandledRef.current) {
        void completeActiveVerse();
      }
      frame = window.requestAnimationFrame(followPlayback);
    };
    frame = window.requestAnimationFrame(followPlayback);
    return () => window.cancelAnimationFrame(frame);
  }, [isPlaying, verse, updateActiveWord, completeActiveVerse]);

  const togglePlayback = useCallback(async () => {
    const audio = audioRef.current;
    if (!audio || !verse) return;
    if (!audio.paused) {
      audio.pause();
      return;
    }
    if (audio.currentTime < verse.start || audio.currentTime >= verse.end - 0.05) {
      repetitionRef.current = 0;
      setRepetitionCycle(1);
      seekToVerse(verse);
    }
    try {
      await audio.play();
    } catch {
      setIsPlaying(false);
    }
  }, [verse, seekToVerse]);

  const resetSession = useCallback(() => {
    const audio = audioRef.current;
    audio?.pause();
    repetitionRef.current = 0;
    resumeAfterVerseRef.current = false;
    setRepetitionCycle(1);
    setIsPlaying(false);
    onActiveAyahChange(fromAyah);
    seekToVerse(visibleAudio?.verses.find((item) => item.ayah === fromAyah) || null);
  }, [fromAyah, visibleAudio, onActiveAyahChange, seekToVerse]);

  return (
    <section className="memorize-player" aria-label="جلسة التكرار">
      <audio
        ref={audioRef}
        src={backendMediaUrl(visibleAudio?.audio_url)}
        preload="metadata"
        onLoadedMetadata={() => seekToVerse(verse)}
        onPause={() => setIsPlaying(false)}
        onPlay={() => setIsPlaying(true)}
        onTimeUpdate={(event) => {
          if (!verse) return;
          const current = event.currentTarget.currentTime;
          setElapsed(Math.max(0, Math.min(duration, current - verse.start)));
          updateActiveWord(current, verse);
          if (current >= verse.end - 0.06 && !boundaryHandledRef.current) {
            void completeActiveVerse();
          }
        }}
      />
      <header className="memorize-player-head">
        <div>
          <span className="reader-panel-kicker">التكرار الموقّت</span>
          <strong>{visibleAudio?.reciter_name_ar || "جارٍ تجهيز القارئ…"}</strong>
          <small>
            الآية {toArabicDigits(activeAyah)} · التكرار {toArabicDigits(repetitionCycle)} من {toArabicDigits(repetition)}
          </small>
        </div>
        <span className={`memorize-player-state${isPlaying ? " is-live" : ""}`}>
          {loading ? "يُحمّل" : isPlaying ? "يُتلى الآن" : "جاهز"}
        </span>
      </header>

      {audioError ? <div className="reader-panel-error" role="alert">{audioError}</div> : null}

      <div className="reader-audio-controls">
        <button
          type="button"
          className="reader-play"
          onClick={() => void togglePlayback()}
          disabled={!verse || loading}
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
            disabled={!verse}
            aria-label="موضع التلاوة داخل آية التثبيت"
            onChange={(event) => {
              const nextElapsed = Number(event.target.value);
              setElapsed(nextElapsed);
              if (audioRef.current && verse) {
                const current = verse.start + nextElapsed;
                audioRef.current.currentTime = current;
                boundaryHandledRef.current = false;
                updateActiveWord(current, verse);
              }
            }}
          />
          <span>{formatTime(elapsed)} / {formatTime(duration)}</span>
        </div>
      </div>

      <div className="memorize-player-options">
        <label><span>القارئ</span>
          <select value={reciterId} onChange={(event) => setReciterId(event.target.value)} disabled={!reciters.length}>
            {reciters.length ? reciters.map((reciter) => (
              <option key={reciter.id} value={reciter.id}>{reciter.name_ar}</option>
            )) : <option>جارٍ تحميل القرّاء…</option>}
          </select>
        </label>
        <label><span>تكرار كل آية</span>
          <select value={repetition} onChange={(event) => {
            repetitionRef.current = 0;
            setRepetitionCycle(1);
            setRepetition(Number(event.target.value) as (typeof repetitionOptions)[number]);
          }}>
            {repetitionOptions.map((count) => (
              <option key={count} value={count}>{toArabicDigits(count)}×</option>
            ))}
          </select>
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
