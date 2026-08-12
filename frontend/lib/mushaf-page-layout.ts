import type { MushafEditionId } from "@/lib/mushaf";

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

function editionMetrics(editionId: MushafEditionId, fontSize: number) {
  const isMadinah = editionId === "digital_khatt" || editionId === "qpc_v2" || editionId === "qpc_v1";
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
    maximumStretch: editionId === "qpc_v1" ? 1.18
      : editionId === "digital_khatt" || editionId === "qpc_v2" ? 1.15
        : editionId === "shamarly" ? 1.5 : Infinity,
  };
}

/** Match the original app's printed-line fit: prefer Quran-font alternates,
 * keep inter-word gaps narrow, then use only a small line-scale correction. */
export function justifyMushafLines(root: HTMLElement, editionId: MushafEditionId) {
  root.querySelectorAll<HTMLElement>(".mushaf-line").forEach((line) => {
    const inner = line.querySelector<HTMLElement>(".mushaf-line-inner");
    if (!inner) return;

    inner.style.fontFeatureSettings = "normal";
    inner.style.fontVariationSettings = "normal";
    inner.style.fontSize = "";
    inner.style.transform = "none";
    inner.style.wordSpacing = "";

    const fontSize = Number.parseFloat(getComputedStyle(inner).fontSize) || 20;
    const metrics = editionMetrics(editionId, fontSize);
    const edgeInset = metrics.isMadinah ? 10 : 6;
    const available = Math.max(0, line.clientWidth - edgeInset);
    if (!available) return;

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
      fitRenderedWidth(inner, line, available, metrics.minimumScale, metrics.maximumStretch);
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
    fitRenderedWidth(inner, line, available, metrics.minimumScale, metrics.maximumStretch);
  });

  // Reconcile after every line has shaped. Chromium can update an earlier
  // line's layout box after a sibling writes OpenType features or spacing.
  root.querySelectorAll<HTMLElement>('.mushaf-line[data-justify="true"]').forEach((line) => {
    const inner = line.querySelector<HTMLElement>(".mushaf-line-inner");
    if (!inner) return;
    const fontSize = Number.parseFloat(getComputedStyle(inner).fontSize) || 20;
    const metrics = editionMetrics(editionId, fontSize);
    const available = Math.max(0, line.clientWidth - (metrics.isMadinah ? 10 : 6));
    if (available) {
      // The printed page contract is stronger than the preferred shaping cap:
      // every ordinary line must land on the same two page edges. Alternates,
      // narrow word spacing, and the gentle cap above remain the first choices;
      // this final pass only closes their residual gap.
      fitRenderedWidth(
        inner,
        line,
        available,
        metrics.minimumScale,
        metrics.stretchOnly ? metrics.maximumStretch : Infinity,
      );
    }
  });
}
