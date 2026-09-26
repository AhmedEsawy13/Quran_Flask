import type {HTMLAttributes, InputHTMLAttributes, ReactNode} from "react";
import {cn} from "@/lib/cn";
import {Button, Field, InputControl, SelectControl, Surface} from "@/components/ui/primitives";
import {DoorIcon} from "@/components/ui/door-icon";
import {waqfTools, type ToolKey} from "@/lib/nav";

/**
 * Compact page heading for the waqf tools: keeps the tool itself above the
 * fold. `tool` places the page on the observe → search → practise path.
 */
export function ToolIntro({
  kicker,
  tool,
  title,
  titleId,
  titleAriaLabel,
  lede,
  children,
}: {
  kicker: string;
  tool?: ToolKey;
  title: string;
  titleId: string;
  titleAriaLabel?: string;
  lede: string;
  children?: ReactNode;
}) {
  const step = tool ? waqfTools.findIndex((item) => item.key === tool) : -1;
  return (
    <section
      className="mx-auto grid w-full max-w-[1120px] items-end gap-x-8 gap-y-3 px-[clamp(14px,4vw,40px)] pt-[clamp(16px,3vw,34px)] pb-[clamp(12px,2vw,22px)] md:grid-cols-[minmax(0,1fr)_auto]"
      aria-labelledby={titleId}
    >
      <div className="grid gap-2">
        <p className="m-0 flex flex-wrap items-center gap-2 text-[0.74rem] font-bold">
          {step >= 0 ? (
            <>
              <span className="text-athar-accent">الوقف والابتداء</span>
              <span aria-hidden="true" className="text-athar-ink-faint">/</span>
            </>
          ) : null}
          <span className="inline-flex items-center gap-1.5 rounded-full border border-athar-gold/25 bg-athar-gold/8 px-2.5 py-0.5 text-athar-gold">
            {tool ? <DoorIcon name={tool} className="size-3.5" /> : <span aria-hidden="true" className="size-1.5 rounded-full bg-athar-gold" />}
            {kicker}
          </span>
          {step >= 0 ? (
            <span className="text-athar-ink-faint" aria-label={`الخطوة ${step + 1} من ${waqfTools.length}`}>
              {waqfTools[step].verb} · {["١", "٢", "٣"][step]} من ٣
            </span>
          ) : null}
        </p>
        <h1
          className="m-0 font-athar-display text-[clamp(1.45rem,3vw,2.3rem)] font-black leading-[1.15] text-balance text-athar-ink [font-feature-settings:'salt'_1]"
          id={titleId}
          aria-label={titleAriaLabel}
        >
          {title}
        </h1>
        <p className="m-0 max-w-[62ch] font-athar-ui text-[0.92rem] leading-[1.7] text-athar-ink-soft">
          {lede}
        </p>
      </div>
      {children ? <div className="flex flex-wrap items-center gap-x-4 gap-y-2 md:justify-end md:pb-1">{children}</div> : null}
    </section>
  );
}

export function ToolChrome({
  label,
  pill,
  note,
  footer,
  className,
  children,
}: {
  label: string;
  pill?: ReactNode;
  note?: ReactNode;
  footer?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={cn(
        "sticky top-[var(--bar-height)] z-40 flex w-full flex-wrap items-end justify-between gap-x-3 gap-y-2 border-b border-athar-line bg-[color-mix(in_srgb,var(--athar-surface)_92%,transparent)] px-[clamp(10px,2.4vw,28px)] py-1.5 shadow-[0_14px_34px_-32px_color-mix(in_srgb,var(--athar-ink)_55%,transparent)] backdrop-blur-[18px] backdrop-saturate-150",
        className,
      )}
      aria-label={label}
    >
      {pill}
      <div className="flex min-w-0 flex-1 flex-wrap items-end gap-3 max-md:basis-full" aria-label="اختيار الموضع">
        {children}
      </div>
      {footer ? (
        <div className="flex w-full min-w-0 basis-full flex-wrap items-center gap-2 border-t border-athar-line-soft pt-2">
          {footer}
        </div>
      ) : null}
      {note ? (
        <p className="m-0 flex w-full items-center justify-center gap-2 border-t border-athar-line bg-athar-accent/5 py-1.5 text-center text-[0.74rem] font-semibold text-athar-ink-soft">
          {note}
        </p>
      ) : null}
    </section>
  );
}

export function ChromePill({
  children,
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement>) {
  if (!children) return null;
  return (
    <span
      className={cn(
        "max-w-[220px] self-center truncate rounded-full border border-athar-line-soft bg-athar-surface px-2.5 py-1 text-[0.7rem] font-semibold text-athar-ink-soft max-md:hidden [&_b]:font-bold [&_b]:text-athar-accent",
        className,
      )}
      {...props}
    >
      {children}
    </span>
  );
}

export function ChromeField({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Field label={label} className={cn("min-w-0 text-[0.74rem] font-semibold text-athar-ink-soft max-md:min-w-[calc(50%-0.4rem)] max-md:flex-1", className)}>
      {children}
    </Field>
  );
}

export function ChromeSelect(props: Parameters<typeof SelectControl>[0]) {
  return (
    <SelectControl
      {...props}
      className={cn("min-h-9 w-auto min-w-[8.25rem] rounded-[10px] py-2 max-md:min-w-0 max-md:w-full", props.className)}
    />
  );
}

export function ChromeInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <InputControl
      {...props}
      className={cn("min-h-9 w-auto min-w-[12rem] rounded-[10px] py-2 max-md:min-w-0 max-md:w-full", props.className)}
    />
  );
}

export function ChromeStepper({
  previousLabel,
  nextLabel,
  previousDisabled,
  nextDisabled,
  onPrevious,
  onNext,
}: {
  previousLabel: string;
  nextLabel: string;
  previousDisabled?: boolean;
  nextDisabled?: boolean;
  onPrevious: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex gap-1.5 self-end">
      <Button
        size="icon"
        variant="secondary"
        className="size-[38px] rounded-[10px] text-lg leading-none"
        aria-label={previousLabel}
        disabled={previousDisabled}
        onClick={onPrevious}
      >
        ›
      </Button>
      <Button
        size="icon"
        variant="secondary"
        className="size-[38px] rounded-[10px] text-lg leading-none"
        aria-label={nextLabel}
        disabled={nextDisabled}
        onClick={onNext}
      >
        ‹
      </Button>
    </div>
  );
}

export function ToolStack({children, className}: {children: ReactNode; className?: string}) {
  return (
    <div className={cn("mx-auto flex w-full max-w-[1120px] flex-col gap-4 px-3 pb-[72px] pt-4 sm:px-5 sm:pt-5", className)}>
      {children}
    </div>
  );
}

export function ToolCard({
  raised = false,
  as = "section",
  className,
  children,
  ...props
}: HTMLAttributes<HTMLElement> & {
  raised?: boolean;
  as?: "div" | "section" | "article" | "aside";
  children: ReactNode;
}) {
  return (
    <Surface
      as={as}
      className={cn("rounded-athar-md p-4", raised && "shadow-athar-sm", className)}
      {...props}
    >
      {children}
    </Surface>
  );
}

export function ToolCardHead({
  title,
  titleId,
  meta,
  children,
}: {
  title: string;
  titleId?: string;
  meta?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2.5">
      <h2 className="m-0 font-athar-display text-[1.08rem] font-bold text-athar-ink" id={titleId}>
        {title}
      </h2>
      {meta ? <span className="text-[0.78rem] text-athar-ink-soft">{meta}</span> : null}
      {children}
    </header>
  );
}
