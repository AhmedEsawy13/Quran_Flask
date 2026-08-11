"use client";

import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type TouchEvent } from "react";
import { cn } from "@/lib/cn";
import type { ReaderView } from "@/lib/mushaf";

type MushafStageProps = {
  children: ReactNode;
  view: ReaderView;
  positionLabel: string;
  previousLabel: string;
  nextLabel: string;
  previousDisabled: boolean;
  nextDisabled: boolean;
  moving?: boolean;
  onPrevious: () => void;
  onNext: () => void;
  className?: string;
};

export function MushafStage({
  children,
  view,
  positionLabel,
  previousLabel,
  nextLabel,
  previousDisabled,
  nextDisabled,
  moving = false,
  onPrevious,
  onNext,
  className,
}: MushafStageProps) {
  const stageRef = useRef<HTMLElement>(null);
  const touchStart = useRef<{x: number; y: number} | null>(null);
  const [fit, setFit] = useState({width: 790, fontSize: 27});

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
        const availableHeight = Math.max(
          430,
          window.innerHeight - Math.max(0, rect.top) - bottomInset - stageChrome,
        );
        const width = Math.floor(Math.min(790, availableWidth, availableHeight * 0.66));
        setFit({
          width,
          fontSize: Math.max(10.5, Math.min(27.5, width / 27)),
        });
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
  }, [view]);

  const style = view === "page" ? {
    "--reader-page-fit-width": `${fit.width}px`,
    "--reader-page-fit-font": `${fit.fontSize}px`,
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
      className={cn("reader-mushaf-stage", className)}
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

      <div className="reader-mushaf-stage-page">{children}</div>

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
