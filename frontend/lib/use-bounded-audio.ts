"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { backendMediaUrl } from "@/lib/paths";

export type BoundedAudioSegment = {
  key: string;
  source: string;
  start: number;
  end: number;
};

const BOUNDARY_EPS = 0.05;
const START_PAD = 0.12;
const END_PAD = 0.1;

function seekTime(start: number) {
  return Math.max(0, start - START_PAD);
}

function stopTime(end: number) {
  return end + END_PAD;
}

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

  const finish = useCallback((segment: BoundedAudioSegment) => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      try {
        audio.currentTime = stopTime(segment.end);
      } catch {
        /* seek can fail while metadata is settling */
      }
    }
    segmentRef.current = null;
    setPlayingKey(null);
    setProgress(1);
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
        audio.currentTime = seekTime(segment.start);
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
    const id = window.setInterval(() => {
      const audio = audioRef.current;
      const segment = segmentRef.current;
      if (!audio || !segment || audio.paused) return;
      const begin = seekTime(segment.start);
      const end = stopTime(segment.end);
      const span = Math.max(0.001, end - begin);
      setProgress(Math.min(1, Math.max(0, audio.currentTime - begin) / span));
      if (audio.currentTime >= end - BOUNDARY_EPS) finish(segment);
    }, 80);
    return () => window.clearInterval(id);
  }, [playingKey, finish]);

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
