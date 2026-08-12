"use client";

import { useEffect, useMemo, useState } from "react";
import type { MushafPage } from "@/lib/api";
import { getTajweedSegments, type TajweedSegment } from "@/lib/tajweed";

const EMPTY_SEGMENTS = new Map<string, TajweedSegment[]>();
const EMPTY_WORD_SEGMENTS = new Map<string, TajweedSegment>();
const AYAH_NUMBER_TOKEN = /^\u06dd?[٠-٩]+$/;

function wordIdentity(word: {word_key?: string; word_index?: number}) {
  if (word.word_key) return word.word_key;
  return Number.isFinite(Number(word.word_index)) ? `#${word.word_index}` : "";
}

function pageVerseKeys(pages: Array<MushafPage | null>) {
  const keys = new Set<string>();
  pages.forEach((page) => page?.lines.forEach((line) => line.words.forEach((word) => {
    const surah = Number(word.surah);
    const ayah = Number(word.ayah);
    if (surah > 0 && ayah > 0) keys.add(`${surah}:${ayah}`);
  })));
  return [...keys];
}

export function usePageTajweed(pages: Array<MushafPage | null>, enabled: boolean) {
  const pageNumbers = pages.map((page) => page?.page_number || 0).join(":");
  const keys = useMemo(() => pageVerseKeys(pages), [pageNumbers]); // eslint-disable-line react-hooks/exhaustive-deps
  const keyString = keys.join("|");
  const [result, setResult] = useState<{key: string; segments: Map<string, TajweedSegment[]>}>({
    key: "",
    segments: EMPTY_SEGMENTS,
  });

  useEffect(() => {
    if (!enabled || !keys.length) return;
    let active = true;
    Promise.all(keys.map(async (key) => {
      const [surah, ayah] = key.split(":").map(Number);
      return [key, await getTajweedSegments(surah, ayah)] as const;
    })).then((entries) => {
      if (active) setResult({key: keyString, segments: new Map(entries)});
    });
    return () => {
      active = false;
    };
  }, [enabled, keyString, keys]);

  const ready = enabled && result.key === keyString;
  const segmentsByWord = useMemo(() => {
    if (!ready) return EMPTY_WORD_SEGMENTS;
    const output = new Map<string, TajweedSegment>();
    const positions = new Map<string, number>();
    pages.forEach((page) => page?.lines.forEach((line) => line.words.forEach((word) => {
      if (word.suppress_render || AYAH_NUMBER_TOKEN.test(word.text.trim())) return;
      const verseKey = `${word.surah}:${word.ayah}`;
      const position = positions.get(verseKey) || 0;
      positions.set(verseKey, position + 1);
      const identity = wordIdentity(word);
      const segment = result.segments.get(verseKey)?.[position];
      if (identity && segment) output.set(identity, segment);
    })));
    return output;
  }, [pages, ready, result.segments]);
  return {
    segmentsByVerse: ready ? result.segments : EMPTY_SEGMENTS,
    segmentsByWord,
    loading: enabled && keys.length > 0 && !ready,
  };
}
