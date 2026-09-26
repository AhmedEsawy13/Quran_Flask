"use client";

import {useEffect, useState} from "react";
import {cn} from "@/lib/cn";
import {mushafFontClass, mushafGlyph} from "@/lib/waqf-lab";
import {waqfMarkLabel} from "@/lib/waqf";

const HAFS = "Uthmanic Hafs";
const WARSH = "Uthmanic Warsh";
const UNITS = 100;

type Box = {x: number; y: number; size: number};

const boxes = new Map<string, Box>();
const pending = new Map<string, Promise<Box | null>>();

/**
 * Waqf marks are combining characters: zero advance, and inked high above the
 * baseline where they would sit over a letter. Measure the real ink box once
 * per font+glyph so it can be drawn centred and at a legible size.
 */
function measure(font: string, text: string): Promise<Box | null> {
  const key = `${font}|${text}`;
  const known = boxes.get(key);
  if (known) return Promise.resolve(known);
  let job = pending.get(key);
  if (!job) {
    job = document.fonts.load(`${UNITS}px "${font}"`, text).then(() => {
      const context = document.createElement("canvas").getContext("2d");
      if (!context) return null;
      context.font = `${UNITS}px "${font}"`;
      context.direction = "ltr";
      context.textAlign = "left";
      const metrics = context.measureText(text);
      const left = -metrics.actualBoundingBoxLeft;
      const right = metrics.actualBoundingBoxRight;
      const top = -metrics.actualBoundingBoxAscent;
      const bottom = metrics.actualBoundingBoxDescent;
      const width = right - left;
      const height = bottom - top;
      if (!(width > 0 && height > 0)) return null;
      // Fill ~72% of the box on the longer side, whatever the glyph's shape.
      const scale = 72 / Math.max(width, height);
      const box = {x: -(left + width / 2) * scale, y: -(top + height / 2) * scale, size: UNITS * scale};
      boxes.set(key, box);
      return box;
    }).catch(() => null);
    pending.set(key, job);
  }
  return job;
}

/**
 * A printed waqf mark drawn from the mushaf's own font (Uthmanic Hafs, or
 * Uthmanic Warsh for ورش), centred in a square — never a plain letter.
 */
export function WaqfGlyph({
  symbol,
  mushafId = "",
  className,
  title,
}: {
  symbol: string;
  mushafId?: string;
  className?: string;
  title?: string;
}) {
  const warsh = mushafFontClass(mushafId) === "font-athar-warsh";
  const font = warsh ? WARSH : HAFS;
  const text = mushafGlyph(symbol, mushafId);
  const [box, setBox] = useState<Box | null>(() => boxes.get(`${font}|${text}`) || null);

  useEffect(() => {
    if (!text) return;
    let live = true;
    void measure(font, text).then((measured) => {
      if (live && measured) setBox(measured);
    });
    return () => {
      live = false;
    };
  }, [font, text]);

  const label = title || waqfMarkLabel(symbol);
  return (
    <svg
      viewBox={`-50 -50 ${UNITS} ${UNITS}`}
      className={cn("inline-block size-[1.6em] shrink-0 overflow-visible align-middle", className)}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      {box ? (
        <text x={box.x} y={box.y} fontSize={box.size} fontFamily={`"${font}", serif`} fill="currentColor" direction="ltr">
          {text}
        </text>
      ) : null}
    </svg>
  );
}
