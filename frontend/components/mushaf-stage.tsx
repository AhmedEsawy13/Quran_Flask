"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type TouchEvent } from "react";
import { cn } from "@/lib/cn";
import type { MushafEditionId, ReaderView } from "@/lib/mushaf";
import { pageAspectRatio } from "@/lib/mushaf-page-layout";

type MushafStageProps = {
  children: ReactNode;
  view: ReaderView;
  editionId?: MushafEditionId;
  pageCount?: 1 | 2;
  zoom?: number;
  positionLabel: string;
  previousLabel: string;
  nextLabel: string;
  previousDisabled: boolean;
  nextDisabled: boolean;
  moving?: boolean;
  onPrevious: () => void;
  onNext: () => void;
  fill?: boolean;
  className?: string;
};

export function MushafStage({
  children,
  view,
  editionId = "digital_khatt",
  pageCount = 1,
  zoom = 1,
  positionLabel,
  previousLabel,
  nextLabel,
  previousDisabled,
  nextDisabled,
  moving = false,
  onPrevious,
  onNext,
  fill = false,
  className,
}: MushafStageProps) {
  const stageRef = useRef<HTMLElement>(null);
  const touchStart = useRef<{x: number; y: number} | null>(null);
  const [fit, setFit] = useState({width: 790, height: 1197});
  const ratio = pageAspectRatio(editionId);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || view !== "page") return;
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const rect = stage.getBoundingClientRect();
        const mobile = window.matchMedia("(max-width: 767px)").matches;
        const bottomInset = mobile ? 82 : 18;
        const stageChrome = mobile ? 60 : 48;
        const horizontalInset = mobile ? 12 : 112;
        const availableWidth = Math.max(280, stage.clientWidth - horizontalInset);
        const availableHeight = fill
          ? Math.max(200, stage.clientHeight - (mobile ? 52 : 40))
          : Math.max(
            mobile ? 430 : 300,
            window.innerHeight - Math.max(0, rect.top) - bottomInset - stageChrome,
          );
        // Match تثبيت sizePages: height-first from aspect ratio, then shrink to width budget.
        const spreadGutter = pageCount === 2 ? 16 : 0;
        const spreadPad = pageCount === 2 ? 20 : 0;
        let height = availableHeight;
        let width = height * ratio;
        const totalWidth = width * pageCount + spreadGutter + spreadPad;
        if (totalWidth > availableWidth) {
          const widthBudget = Math.max(1, availableWidth - spreadGutter - spreadPad);
          const scale = widthBudget / (width * pageCount);
          width *= scale;
          height *= scale;
        }
        width = Math.max(150, Math.floor(Math.min(790, width)));
        height = Math.max(230, Math.floor(width / ratio));
        setFit({ width, height });
      });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(stage);
    window.addEventListener("resize", measure);
    measure();
    return () => {
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [editionId, fill, pageCount, ratio, view]);

  const zoomed = Math.abs(zoom - 1) > 0.001;
  const spreadGutter = pageCount === 2 ? 36 : 0;
  const baseWidth = fit.width * pageCount + spreadGutter;
  const style = view === "page" ? {
    "--reader-page-fit-width": `${fit.width}px`,
    "--reader-page-fit-height": `${fit.height}px`,
    "--reader-page-aspect": String(ratio),
  } as CSSProperties : undefined;

  const finishSwipe = (event: TouchEvent<HTMLElement>) => {
    const start = touchStart.current;
    touchStart.current = null;
    if (!start || event.changedTouches.length !== 1 || moving) return;
    const touch = event.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < 48 || Math.abs(dx) < Math.abs(dy) * 1.25) return;
    if (dx < 0 && !nextDisabled) onNext();
    if (dx > 0 && !previousDisabled) onPrevious();
  };

  return (
    <section
      ref={stageRef}
      className={cn("reader-mushaf-stage", fill && "is-fill", zoomed && "is-zoomed", className)}
      data-page-count={pageCount}
      data-zoom={zoom.toFixed(1)}
      aria-label={`موضع القراءة — ${positionLabel}`}
      aria-busy={moving}
      style={style}
      onTouchStart={(event) => {
        if (event.touches.length !== 1) return;
        const target = event.target as HTMLElement;
        if (target.closest("button, a, input, select, summary")) return;
        touchStart.current = {x: event.touches[0].clientX, y: event.touches[0].clientY};
      }}
      onTouchEnd={finishSwipe}
      onTouchCancel={() => {
        touchStart.current = null;
      }}
    >
      <button
        type="button"
        className="reader-edge-nav is-previous"
        aria-label={previousLabel}
        title={previousLabel}
        disabled={previousDisabled || moving}
        onClick={onPrevious}
      >
        <span aria-hidden="true">›</span>
      </button>

      <div className="reader-mushaf-stage-page">
        <div
          className="reader-mushaf-zoom-shell"
          style={zoomed ? {width: baseWidth * zoom, height: fit.height * zoom} : undefined}
        >
          <div
            className="reader-mushaf-zoom-spread"
            style={zoomed ? {
              width: baseWidth,
              height: fit.height,
              transform: `scale(${zoom})`,
            } : undefined}
          >
            {children}
          </div>
        </div>
      </div>

      <button
        type="button"
        className="reader-edge-nav is-next"
        aria-label={nextLabel}
        title={nextLabel}
        disabled={nextDisabled || moving}
        onClick={onNext}
      >
        <span aria-hidden="true">‹</span>
      </button>

      <span className="reader-stage-position">{positionLabel}</span>
      <span className="reader-stage-swipe-hint">اسحب للتنقّل</span>
    </section>
  );
}
