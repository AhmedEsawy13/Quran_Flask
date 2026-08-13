import type {HTMLAttributes, InputHTMLAttributes, ReactNode} from "react";
import {cn} from "@/lib/cn";
import {Button, Field, InputControl, SelectControl, Surface} from "@/components/ui/primitives";

export function ToolIntro({
  kicker,
  title,
  titleId,
  titleAriaLabel,
  lede,
  children,
}: {
  kicker: string;
  title: string;
  titleId: string;
  titleAriaLabel?: string;
  lede: string;
  children?: ReactNode;
}) {
  return (
    <section
      className="mx-auto grid w-full max-w-[1120px] gap-3 px-[clamp(16px,4vw,40px)] pt-[clamp(28px,5vw,52px)] pb-[clamp(18px,3vw,28px)]"
      aria-labelledby={titleId}
    >
      <p className="m-0 text-[0.78rem] font-bold tracking-[0.04em] text-athar-gold">{kicker}</p>
      <h1
        className="m-0 max-w-[18ch] font-athar-display text-[clamp(1.85rem,4.2vw,3.2rem)] font-black leading-[1.08] text-balance text-athar-ink [font-feature-settings:'salt'_1]"
        id={titleId}
        aria-label={titleAriaLabel}
      >
        {title}
      </h1>
      <p className="m-0 max-w-[48ch] font-serif text-[clamp(0.88rem,1.4vw,1.02rem)] leading-[1.7] text-athar-ink-soft">
        {lede}
      </p>
      {children ? <div className="mt-1 flex flex-wrap gap-x-4 gap-y-2.5">{children}</div> : null}
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
        "sticky top-[var(--bar-height)] z-40 flex w-full flex-wrap items-end justify-between gap-x-[18px] gap-y-3 border-b border-athar-line bg-[color-mix(in_srgb,var(--athar-surface)_92%,transparent)] px-[clamp(12px,2.4vw,28px)] py-2 shadow-[0_14px_34px_-32px_color-mix(in_srgb,var(--athar-ink)_55%,transparent)] backdrop-blur-[18px] backdrop-saturate-150",
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
        "max-w-[220px] self-center truncate rounded-full border border-athar-line-soft bg-athar-surface px-2.5 py-1 text-[0.7rem] font-semibold text-athar-ink-soft [&_b]:font-bold [&_b]:text-athar-accent",
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
    <Field label={label} className={cn("min-w-0 text-[0.74rem] font-semibold text-athar-ink-soft", className)}>
      {children}
    </Field>
  );
}

export function ChromeSelect(props: Parameters<typeof SelectControl>[0]) {
  return (
    <SelectControl
      {...props}
      className={cn("min-h-9 w-auto min-w-[8.25rem] rounded-[10px] py-2", props.className)}
    />
  );
}

export function ChromeInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <InputControl
      {...props}
      className={cn("min-h-9 w-auto min-w-[12rem] rounded-[10px] py-2", props.className)}
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
    <div className={cn("mx-auto flex w-full max-w-[1120px] flex-col gap-4 px-5 pb-[72px] pt-5", className)}>
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
