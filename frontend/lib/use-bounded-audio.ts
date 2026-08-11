"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { backendMediaUrl } from "@/lib/paths";

export type BoundedAudioSegment = {
  key: string;
  source: string;
  start: number;
  end: number;
};

export function useBoundedAudio() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const sourceRef = useRef("");
  const segmentRef = useRef<BoundedAudioSegment | null>(null);
  const generationRef = useRef(0);
  const [playingKey, setPlayingKey] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  const stop = useCallback(() => {
    generationRef.current += 1;
    segmentRef.current = null;
    audioRef.current?.pause();
    setPlayingKey(null);
    setProgress(0);
  }, []);

  const play = useCallback(async (segment: BoundedAudioSegment) => {
    const audio = audioRef.current;
    if (!audio || !segment.source || segment.end <= segment.start) return;
    if (playingKey === segment.key && !audio.paused) {
      stop();
      return;
    }

    const generation = ++generationRef.current;
    segmentRef.current = segment;
    setPlayingKey(segment.key);
    setProgress(0);
    const source = backendMediaUrl(segment.source);
    if (!source) return;

    const begin = async () => {
      if (generation !== generationRef.current || segmentRef.current?.key !== segment.key) return;
      try {
        audio.currentTime = segment.start;
        await audio.play();
      } catch {
        if (generation === generationRef.current) {
          setPlayingKey(null);
          setProgress(0);
        }
      }
    };

    if (sourceRef.current !== source) {
      sourceRef.current = source;
      audio.src = source;
      audio.load();
    }
    if (audio.readyState >= 1) await begin();
    else audio.addEventListener("loadedmetadata", () => void begin(), {once: true});
  }, [playingKey, stop]);

  useEffect(() => {
    if (!playingKey) return;
    let frame = 0;
    const follow = () => {
      const audio = audioRef.current;
      const segment = segmentRef.current;
      if (!audio || !segment || audio.paused) return;
      const span = Math.max(0.001, segment.end - segment.start);
      const elapsed = Math.max(0, audio.currentTime - segment.start);
      setProgress(Math.min(1, elapsed / span));
      if (audio.currentTime >= segment.end - 0.04) {
        audio.pause();
        segmentRef.current = null;
        setPlayingKey(null);
        setProgress(1);
        return;
      }
      frame = window.requestAnimationFrame(follow);
    };
    frame = window.requestAnimationFrame(follow);
    return () => window.cancelAnimationFrame(frame);
  }, [playingKey]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const reset = () => {
      segmentRef.current = null;
      setPlayingKey(null);
      setProgress(0);
    };
    audio.addEventListener("ended", reset);
    audio.addEventListener("error", reset);
    return () => {
      audio.removeEventListener("ended", reset);
      audio.removeEventListener("error", reset);
    };
  }, []);

  useEffect(() => () => {
    generationRef.current += 1;
    audioRef.current?.pause();
  }, []);

  return {audioRef, playingKey, progress, play, stop};
}
