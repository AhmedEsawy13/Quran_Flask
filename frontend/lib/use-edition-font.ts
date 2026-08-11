"use client";

import { useEffect, useState } from "react";
import { MUSHAF_EDITIONS, type MushafEditionId } from "@/lib/mushaf";

const loadedFonts = new Map<string, Promise<void>>();

export function useEditionFont(editionId: MushafEditionId) {
  const [fontLoading, setFontLoading] = useState(false);

  useEffect(() => {
    const descriptor = MUSHAF_EDITIONS[editionId].font;
    if (!descriptor || typeof FontFace === "undefined") return;
    let active = true;
    let promise = loadedFonts.get(descriptor.family);
    if (!promise) {
      const face = new FontFace(descriptor.family, `url("${descriptor.url}")`);
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
  }, [editionId]);

  return fontLoading;
}
