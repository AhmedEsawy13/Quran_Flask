import {cn} from "@/lib/cn";
import {WAQF_GLYPH_PATHS, type GlyphOutline} from "@/lib/waqf-glyph-paths";
import {mushafFontClass, mushafGlyph} from "@/lib/waqf-lab";
import {waqfMarkLabel} from "@/lib/waqf";

/** Font-unit height of the commonest printed marks (صلى، قلى، ج): the reference for print size. */
export const WAQF_GLYPH_REFERENCE_HEIGHT = (["\u06D6", "\u06D7", "\u06DA"] as const)
  .map((char) => WAQF_GLYPH_PATHS.hafs[char].box)
  .reduce((total, box) => total + (box[3] - box[1]), 0) / 3;

/** Font-unit size of a mark as WaqfGlyph lays it out (several marks side by side). */
export function waqfGlyphSize(symbol: string, mushafId = "") {
  const warsh = mushafFontClass(mushafId) === "font-athar-warsh";
  const outlines = [...mushafGlyph(symbol, mushafId)]
    .map((char) => (warsh && WAQF_GLYPH_PATHS.warsh[char]) || WAQF_GLYPH_PATHS.hafs[char])
    .filter((outline): outline is GlyphOutline => Boolean(outline));
  const tallest = Math.max(1, ...outlines.map(({box}) => box[3] - box[1]));
  const widths = outlines.map(({box}) => box[2] - box[0]);
  const width = widths.reduce((total, value) => total + value, 0) + tallest * 0.18 * Math.max(0, widths.length - 1);
  return {width: Math.max(1, width), height: tallest};
}

/** Share of the box the mark fills on its longer side. */
const FILL = 0.72;

/**
 * A printed waqf mark drawn from the mushaf's own font outlines (Uthmanic
 * Hafs, or Uthmanic Warsh for ورش), centred in a square — never a letter.
 *
 * The outlines are pre-extracted (scripts/build_waqf_glyph_paths.py) rather
 * than typeset: a lone combining mark has no advance and is inked far above
 * the baseline, and WebKit measures it as empty, so text rendering left
 * Safari blank. Paths render identically everywhere, with no font loading.
 */
export function WaqfGlyph({
  symbol,
  mushafId = "",
  className,
  title,
  fit = "square",
}: {
  symbol: string;
  mushafId?: string;
  className?: string;
  title?: string;
  /** "square": centred with breathing room. "box": ink fills the element exactly (to replace a printed mark in place). */
  fit?: "square" | "box";
}) {
  const warsh = mushafFontClass(mushafId) === "font-athar-warsh";
  const outlines = [...mushafGlyph(symbol, mushafId)]
    .map((char) => (warsh && WAQF_GLYPH_PATHS.warsh[char]) || WAQF_GLYPH_PATHS.hafs[char])
    .filter((outline): outline is GlyphOutline => Boolean(outline));
  const label = title || waqfMarkLabel(symbol);

  // Several marks (e.g. Warsh «ر،ص») sit side by side, first on the right.
  const tallest = Math.max(1, ...outlines.map(({box}) => box[3] - box[1]));
  const gap = tallest * 0.18;
  let cursor = 0;
  const placed = outlines.map((outline) => {
    const [xMin, yMin, xMax, yMax] = outline.box;
    const width = xMax - xMin;
    const dx = -cursor - width - xMin;
    const dy = (yMin + yMax) / 2;
    cursor += width + gap;
    return {outline, dx, dy};
  });
  const totalWidth = Math.max(1, cursor - gap);
  const side = Math.max(totalWidth, tallest) / FILL;
  const viewBox = fit === "box"
    ? `${-totalWidth} ${-tallest / 2} ${totalWidth} ${tallest}`
    : `${-totalWidth / 2 - side / 2} ${-side / 2} ${side} ${side}`;

  return (
    <svg
      viewBox={viewBox}
      preserveAspectRatio="xMidYMid meet"
      className={cn("inline-block size-[1.6em] shrink-0 align-middle", className)}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      {placed.map(({outline, dx, dy}, index) => (
        <path key={index} d={outline.d} transform={`translate(${dx} ${dy}) scale(1 -1)`} fill="currentColor" />
      ))}
    </svg>
  );
}
