"use client";

import {useEffect, useMemo, useRef, useState, type CSSProperties} from "react";
import type {MushafPage, Surah} from "@/lib/api";
import {pageAspectRatio} from "@/lib/mushaf-page-layout";
import {useEditionFont} from "@/lib/use-edition-font";
import {MushafRenderer, type PracticeTap} from "@/components/mushaf-renderer";
import {assignPracticePositions, practiceEditionId} from "@/lib/practice-pages";

export function PracticeMushafPages({
  pages,
  surahs,
  selectedSurah,
  surahNumber,
  fromAyah,
  toAyah,
  mushaf,
  versesLastWpos,
  stops,
  onWordTap,
  onRetry,
}: {
  pages: MushafPage[];
  surahs: Surah[];
  selectedSurah: Surah | undefined;
  surahNumber: number;
  fromAyah: number;
  toAyah: number;
  mushaf: string;
  versesLastWpos: ReadonlyMap<number, number>;
  stops: ReadonlySet<string>;
  onWordTap: (ayah: number, wpos: number) => void;
  onRetry: () => void;
}) {
  const editionId = practiceEditionId(mushaf);
  const fontLoading = useEditionFont(editionId);
  const hostRef = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState({width: 560, height: 920});
  const positions = useMemo(() => assignPracticePositions(pages), [pages]);
  const practice = useMemo<PracticeTap>(() => ({
    surah: surahNumber,
    fromAyah,
    toAyah,
    stopKeys: stops,
    positions,
    lastWpos: versesLastWpos,
    onWordTap,
  }), [fromAyah, onWordTap, positions, stops, surahNumber, toAyah, versesLastWpos]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const measure = () => {
      const ratio = pageAspectRatio(editionId);
      const width = Math.max(240, Math.min(host.clientWidth - 8, 560));
      setFit({width, height: Math.round(width / ratio + 72)});
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(host);
    measure();
    return () => observer?.disconnect();
  }, [editionId, pages.length]);

  return (
    <div
      ref={hostRef}
      className="practice-mushaf-pages"
      style={{
        "--reader-page-fit-width": `${fit.width}px`,
        "--reader-page-fit-height": `${fit.height}px`,
      } as CSSProperties}
    >
      {pages.map((page) => (
        <MushafRenderer
          key={page.page_number}
          view="page"
          editionId={editionId}
          ayah={null}
          page={page}
          surahs={surahs}
          selectedSurah={selectedSurah}
          surahNumber={surahNumber}
          ayahNumber={fromAyah}
          isLoading={false}
          error=""
          fontLoading={fontLoading}
          activeAudioWord={null}
          waqfEnabled
          waqfSource={mushaf}
          practice={practice}
          onRetry={onRetry}
        />
      ))}
    </div>
  );
}
