import type { MushafEditionId } from "@/lib/mushaf";

type LayoutOptions = {
  dual?: boolean;
  linesPerPage?: number;
};

function isMadinahEdition(editionId: MushafEditionId) {
  return editionId === "digital_khatt" || editionId === "qpc_v2" || editionId === "qpc_v1";
}

function digitalKhattFeatureCandidates() {
  return [
    "'jalt' 1",
    "'jalt' 1, 'cv02' 1",
    "'jalt' 1, 'cv03' 1",
    "'jalt' 1, 'cv02' 1, 'cv03' 1",
    "'jalt' 1, 'cv01' 1",
    "'jalt' 1, 'cv01' 1, 'cv02' 1",
    "'jalt' 1, 'cv01' 1, 'cv03' 1",
    "'jalt' 1, 'cv01' 1, 'cv02' 1, 'cv03' 1",
  ];
}

function oldMadinaFeatureCandidates() {
  return [
    ["cv02"], ["cv03"], ["cv02", "cv03"], ["cv01"],
    ["cv01", "cv02"], ["cv01", "cv03"], ["cv01", "cv02", "cv03"],
  ].map((tags) => ["'salt' 1", ...tags.map((tag) => `'${tag}' 1`)].join(", "));
}

function renderedWidth(inner: HTMLElement, line: HTMLElement) {
  const visualInnerWidth = inner.getBoundingClientRect().width;
  const layoutLineWidth = line.clientWidth;
  const visualLineWidth = line.getBoundingClientRect().width;
  if (!visualInnerWidth || !layoutLineWidth || !visualLineWidth) return visualInnerWidth;
  const inheritedScale = visualLineWidth / layoutLineWidth;
  return inheritedScale > 0 ? visualInnerWidth / inheritedScale : visualInnerWidth;
}

function fitRenderedWidth(
  inner: HTMLElement,
  line: HTMLElement,
  available: number,
  minimumScale: number,
  maximumScale: number,
) {
  const lower = Math.max(0.5, minimumScale || 0.5);
  const upper = Number.isFinite(maximumScale)
    ? Math.max(lower, maximumScale)
    : Infinity;
  for (let pass = 0; pass < 4; pass += 1) {
    const width = renderedWidth(inner, line);
    if (!width || Math.abs(width - available) <= 0.25) return;
    const matrix = getComputedStyle(inner).transform.match(/^matrix\(([^,]+)/);
    const currentScale = matrix ? Number(matrix[1]) : 1;
    if (!Number.isFinite(currentScale) || currentScale <= 0) return;
    const desiredScale = currentScale * available / width;
    if (desiredScale < lower) {
      const currentSize = Number.parseFloat(getComputedStyle(inner).fontSize) || 0;
      if (!currentSize) return;
      inner.style.fontSize = `${currentSize * desiredScale / lower}px`;
      inner.style.transform = `scaleX(${lower})`;
      continue;
    }
    const nextScale = Math.max(lower, Math.min(upper, desiredScale));
    inner.style.transform = `scaleX(${nextScale})`;
  }
}

function editionMetrics(editionId: MushafEditionId, fontSize: number, options: LayoutOptions = {}) {
  const isMadinah = isMadinahEdition(editionId);
  // Match static/js/mushaf_memorize.js: dual spreads use 1.20 for every source.
  const maximumStretch = options.dual ? 1.20
    : editionId === "qpc_v1" ? 1.18
      : editionId === "digital_khatt" || editionId === "qpc_v2" ? 1.15
        : editionId === "shamarly" ? 1.5
          : Infinity;
  return {
    isMadinah,
    stretchOnly: editionId === "shamarly",
    candidates: editionId === "qpc_v1"
      ? oldMadinaFeatureCandidates()
      : editionId === "digital_khatt" || editionId === "qpc_v2"
        ? digitalKhattFeatureCandidates()
        : [],
    minimumScale: isMadinah ? 0.95 : 0.72,
    minimumFeatureScale: isMadinah ? 0.95 : 1,
    minimumWordSpacing: isMadinah ? Math.max(0.8, Math.min(1.8, fontSize * 0.07)) : 0,
    maximumWordSpacing: isMadinah ? Math.max(1.5, Math.min(4, fontSize * 0.12)) : Infinity,
    maximumStretch,
  };
}

/**
 * Port of AtharPageChrome.createFontSizer for one page.
 * Measure natural line widths at a height-based seed size, then pick a page
 * font so a typical line nearly fills the text column before justify runs.
 */
export function fitMushafFontSize(
  pageEl: HTMLElement,
  editionId: MushafEditionId,
  options: LayoutOptions = {},
) {
  const linesPerPage = Math.max(1, options.linesPerPage || 15);
  const isMadinah = isMadinahEdition(editionId);
  const minLineScale = isMadinah ? 0.95 : 0;
  const minFontSize = 9.5;
  const height = pageEl.clientHeight || 1;
  const lineHeight = height / linesPerPage;
  const maxFontSize = lineHeight * 0.92;
  let fontSize = Math.max(minFontSize, lineHeight * 0.62);
  writePageFitFont(pageEl, fontSize);
  // Flush so ratio measurements use the seed size, not a stale computed font.
  void pageEl.offsetHeight;

  let inners = [
    ...pageEl.querySelectorAll<HTMLElement>('.mushaf-line[data-justify="true"] .mushaf-line-inner'),
  ];
  if (!inners.length) {
    inners = [...pageEl.querySelectorAll<HTMLElement>(".mushaf-line .mushaf-line-inner")];
  }

  const ratios: number[] = [];
  inners.forEach((inner) => {
    inner.style.transform = "none";
    inner.style.fontSize = "";
    inner.style.fontFeatureSettings = "normal";
    inner.style.fontVariationSettings = "normal";
    inner.style.wordSpacing = "";
    const line = inner.parentElement;
    const available = line?.clientWidth || 0;
    const natural = inner.scrollWidth;
    if (natural > 0 && available > 0) ratios.push(available / natural);
  });

  if (ratios.length) {
    ratios.sort((a, b) => a - b);
    const median = ratios[Math.floor(ratios.length / 2)] || 1;
    const typicalFit = fontSize * median * 0.98;
    const compressionFit = minLineScale > 0
      ? fontSize * ratios[0] * 0.99 / minLineScale
      : Infinity;
    fontSize = Math.max(minFontSize, Math.min(maxFontSize, typicalFit, compressionFit));
  }

  writePageFitFont(pageEl, fontSize);
  void pageEl.offsetHeight;

  // Second pass: shaping is not linear with font-size. If the longest line still
  // needs more than the allowed scaleX crush, drop the page font (avoids
  // "stuck" compressed glyphs vs تثبيت).
  if (minLineScale > 0 && inners.length) {
    let worstRatio = Infinity;
    inners.forEach((inner) => {
      inner.style.transform = "none";
      inner.style.fontSize = "";
      inner.style.fontFeatureSettings = "normal";
      inner.style.fontVariationSettings = "normal";
      inner.style.wordSpacing = "";
      const line = inner.parentElement;
      const available = line?.clientWidth || 0;
      const natural = inner.scrollWidth;
      if (natural > 0 && available > 0) worstRatio = Math.min(worstRatio, available / natural);
    });
    if (Number.isFinite(worstRatio) && worstRatio < minLineScale) {
      fontSize = Math.max(minFontSize, fontSize * worstRatio * 0.99 / minLineScale);
      writePageFitFont(pageEl, fontSize);
    }
  }

  return fontSize;
}

/** Prefer .mushaf-lines so React `style` on the page article cannot wipe the var. */
function writePageFitFont(pageEl: HTMLElement, fontSize: number) {
  const value = `${fontSize}px`;
  pageEl.style.setProperty("--reader-page-fit-font", value);
  pageEl.querySelector<HTMLElement>(".mushaf-lines")?.style.setProperty("--reader-page-fit-font", value);
}

/** Match تثبيت printed-line fit: measured font → OpenType → spacing → capped scaleX. */
export function justifyMushafLines(
  root: HTMLElement,
  editionId: MushafEditionId,
  options: LayoutOptions = {},
) {
  root.querySelectorAll<HTMLElement>(".mushaf-line").forEach((line) => {
    const inner = line.querySelector<HTMLElement>(".mushaf-line-inner");
    if (!inner) return;

    inner.style.fontFeatureSettings = "normal";
    inner.style.fontVariationSettings = "normal";
    inner.style.fontSize = "";
    inner.style.transform = "none";
    inner.style.wordSpacing = "";

    const fontSize = Number.parseFloat(getComputedStyle(inner).fontSize) || 20;
    const metrics = editionMetrics(editionId, fontSize, options);
    const edgeInset = metrics.isMadinah ? 10 : 6;
    const available = Math.max(0, line.clientWidth - edgeInset);
    if (!available) return;

    // Centered/special lines: only clamp overflow, never stretch to fill.
    if (line.dataset.justify !== "true") {
      const natural = renderedWidth(inner, line);
      if (natural > available + 0.5) {
        inner.style.transform = `scaleX(${Math.max(0.72, available / natural)})`;
      }
      return;
    }

    if (metrics.minimumWordSpacing > 0) {
      inner.style.wordSpacing = `${metrics.minimumWordSpacing}px`;
    }
    const natural = renderedWidth(inner, line);
    if (!natural) return;

    if (natural > available + 0.5) {
      const rawScale = Math.max(0.5, available / natural);
      if (rawScale < metrics.minimumScale) {
        inner.style.fontSize = `${fontSize * rawScale / metrics.minimumScale}px`;
        inner.style.transform = `scaleX(${metrics.minimumScale})`;
        for (let pass = 0; pass < 3; pass += 1) {
          const width = renderedWidth(inner, line);
          if (!width || width <= available + 0.25) break;
          const currentSize = Number.parseFloat(getComputedStyle(inner).fontSize) || 0;
          if (!currentSize) break;
          inner.style.fontSize = `${currentSize * available / width}px`;
        }
        const width = renderedWidth(inner, line);
        if (width > 0) {
          inner.style.transform = `scaleX(${Math.max(
            metrics.minimumScale,
            Math.min(1, metrics.minimumScale * available / width),
          )})`;
        }
        fitRenderedWidth(inner, line, available, metrics.minimumScale, 1);
        return;
      }
      inner.style.transform = `scaleX(${rawScale})`;
      fitRenderedWidth(inner, line, available, metrics.minimumScale, 1);
      return;
    }

    if (metrics.stretchOnly) {
      inner.style.transform = `scaleX(${Math.min(metrics.maximumStretch, available / natural)})`;
      fitRenderedWidth(inner, line, available, 0.5, metrics.maximumStretch);
      return;
    }

    let selectedFeatures = "";
    let selectedWidth = natural;
    let closestDistance = Math.abs(available - natural);
    metrics.candidates.forEach((candidate) => {
      inner.style.fontFeatureSettings = candidate;
      const candidateWidth = renderedWidth(inner, line);
      if (!candidateWidth) return;
      const scale = available / candidateWidth;
      if (candidateWidth > available + 0.5 && scale < metrics.minimumFeatureScale) return;
      const distance = Math.abs(available - candidateWidth);
      if (distance + 0.25 < closestDistance) {
        closestDistance = distance;
        selectedFeatures = candidate;
        selectedWidth = candidateWidth;
      }
    });
    inner.style.fontFeatureSettings = selectedFeatures || "normal";

    if (selectedWidth > available + 0.5) {
      inner.style.transform = `scaleX(${available / selectedWidth})`;
      fitRenderedWidth(inner, line, available, metrics.minimumFeatureScale, metrics.maximumStretch);
      return;
    }

    const gaps = Math.max(0, inner.querySelectorAll(".mushaf-word").length - 1);
    const slack = available - selectedWidth;
    if (slack > 0.5 && gaps > 0) {
      const spacing = Math.min(
        metrics.minimumWordSpacing + slack / gaps,
        metrics.maximumWordSpacing,
      );
      if (spacing > 0) inner.style.wordSpacing = `${spacing}px`;
      const spacedWidth = renderedWidth(inner, line);
      if (spacedWidth > 0 && spacedWidth < available - 0.5) {
        const stretch = Math.min(available / spacedWidth, metrics.maximumStretch);
        if (stretch > 1.0005) inner.style.transform = `scaleX(${stretch})`;
      }
    } else if (slack > 0.5) {
      inner.style.transform = `scaleX(${Math.min(available / selectedWidth, metrics.maximumStretch)})`;
    }
    fitRenderedWidth(inner, line, available, metrics.minimumFeatureScale, metrics.maximumStretch);
  });

  root.querySelectorAll<HTMLElement>('.mushaf-line[data-justify="true"]').forEach((line) => {
    const inner = line.querySelector<HTMLElement>(".mushaf-line-inner");
    if (!inner) return;
    const fontSize = Number.parseFloat(getComputedStyle(inner).fontSize) || 20;
    const metrics = editionMetrics(editionId, fontSize, options);
    const available = Math.max(0, line.clientWidth - (metrics.isMadinah ? 10 : 6));
    if (!available) return;
    fitRenderedWidth(
      inner,
      line,
      available,
      metrics.minimumScale,
      Math.max(1, metrics.maximumStretch),
    );
  });
}

/** Same order as تثبيت: measure page font, then justify lines. */
export function fitAndJustifyMushafPage(
  pageEl: HTMLElement,
  editionId: MushafEditionId,
  options: LayoutOptions = {},
) {
  const fontSize = fitMushafFontSize(pageEl, editionId, options);
  // Fitted font is a CSS variable — force layout before width-based justify.
  void pageEl.offsetHeight;
  justifyMushafLines(pageEl, editionId, options);
  return fontSize;
}

export function pageAspectRatio(editionId: MushafEditionId) {
  return editionId === "qpc_v1" ? 0.72 : 0.66;
}
