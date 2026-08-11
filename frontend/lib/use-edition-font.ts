"use client";

import { useEffect, useState } from "react";
import { MUSHAF_EDITIONS, type MushafEditionId } from "@/lib/mushaf";

const loadedFonts = new Map<string, Promise<void>>();

export function useEditionFont(editionId: MushafEditionId, pageFontName?: string) {
  const [fontLoading, setFontLoading] = useState(false);

  useEffect(() => {
    const edition = MUSHAF_EDITIONS[editionId];
    const usesPageFont = "dynamicPageFont" in edition && edition.dynamicPageFont &&
      Boolean(pageFontName && /^[A-Za-z0-9-]+$/.test(pageFontName));
    const descriptor = usesPageFont
      ? {family: pageFontName as string, url: `/backend-fonts/${encodeURIComponent(pageFontName as string)}.woff2`}
      : edition.font;
    if (!descriptor || typeof FontFace === "undefined") return;
    let active = true;
    let promise = loadedFonts.get(descriptor.family);
    if (!promise) {
      const face = new FontFace(descriptor.family, `url("${descriptor.url}")`, {display: "swap"});
      promise = face.load().then((loadedFace) => {
        document.fonts.add(loadedFace);
      });
      loadedFonts.set(descriptor.family, promise);
    }
    queueMicrotask(() => {
      if (active) setFontLoading(true);
    });
    promise
      .catch(() => {
        loadedFonts.delete(descriptor.family);
      })
      .finally(() => {
        if (active) setFontLoading(false);
      });
    return () => {
      active = false;
    };
  }, [editionId, pageFontName]);

  return fontLoading;
}
