"use client";

import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ChangeEventHandler,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";
import {cn} from "@/lib/cn";

type ButtonVariant = "primary" | "secondary" | "quiet" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg" | "icon";

const buttonVariants: Record<ButtonVariant, string> = {
  primary: "border-athar-accent bg-athar-accent text-athar-on-accent shadow-sm hover:bg-athar-accent-soft",
  secondary: "border-athar-line bg-athar-surface text-athar-ink hover:border-athar-accent hover:text-athar-accent",
  quiet: "border-athar-line-soft bg-athar-line-soft text-athar-ink-soft hover:bg-athar-line hover:text-athar-ink",
  ghost: "border-transparent bg-transparent text-athar-ink-soft hover:bg-athar-line-soft hover:text-athar-ink",
  danger: "border-red-700/25 bg-red-700/8 text-red-800 hover:bg-red-700/12",
};

const buttonSizes: Record<ButtonSize, string> = {
  sm: "min-h-9 rounded-[10px] px-3 py-1.5 text-xs",
  md: "min-h-11 rounded-xl px-4 py-2 text-sm",
  lg: "min-h-12 rounded-[14px] px-5 py-2.5 text-base",
  icon: "size-11 rounded-full p-0",
};

export function Button({
  className,
  variant = "secondary",
  size = "md",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {variant?: ButtonVariant; size?: ButtonSize}) {
  return (
    <button
      type={type}
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 border font-athar-ui font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent",
        buttonVariants[variant],
        buttonSizes[size],
        className,
      )}
      {...props}
    />
  );
}

export function IconButton({label, className, ...props}: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "aria-label"> & {label: string}) {
  return <Button aria-label={label} title={label} size="icon" variant="ghost" className={className} {...props} />;
}

type SurfaceVariant = "panel" | "subtle" | "toolbar";
const surfaceVariants: Record<SurfaceVariant, string> = {
  panel: "border-athar-line bg-athar-surface shadow-athar-sm",
  subtle: "border-athar-line-soft bg-athar-line-soft",
  toolbar: "border-athar-line bg-[color-mix(in_srgb,var(--athar-surface)_90%,transparent)] shadow-athar-sm backdrop-blur-xl",
};

export function Surface({
  as: Component = "div",
  variant = "panel",
  className,
  ...props
}: HTMLAttributes<HTMLElement> & {as?: "div" | "section" | "article" | "aside"; variant?: SurfaceVariant}) {
  return <Component className={cn("min-w-0 border", surfaceVariants[variant], className)} {...props} />;
}

export function RouteSkeleton({label}: {label: string}) {
  return (
    <div className="grid min-h-[520px] gap-4" aria-label={label} role="status">
      <span className="min-h-[72px] animate-pulse rounded-athar-md border border-athar-line bg-athar-surface" />
      <span className="animate-pulse rounded-athar-md border border-athar-line bg-athar-surface" />
    </div>
  );
}

export function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label className={cn("grid min-w-0 gap-1 text-[0.7rem] text-athar-ink-faint", className)}>
      <span>{label}</span>
      {children}
      {hint ? <small className="text-[0.65rem] text-athar-ink-faint">{hint}</small> : null}
    </label>
  );
}

export function SelectControl({className, ...props}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "min-h-11 w-full rounded-xl border border-athar-line bg-athar-surface px-3 py-2 text-sm text-athar-ink outline-none transition-colors disabled:cursor-wait disabled:opacity-50 focus:border-athar-accent focus:ring-2 focus:ring-athar-accent/15",
        className,
      )}
      {...props}
    />
  );
}

export function InputControl({className, ...props}: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "min-h-11 w-full rounded-xl border border-athar-line bg-athar-surface px-3 py-2 text-sm text-athar-ink outline-none transition-colors disabled:cursor-wait disabled:opacity-50 focus:border-athar-accent focus:ring-2 focus:ring-athar-accent/15",
        className,
      )}
      {...props}
    />
  );
}

export function CheckControl({
  label,
  checked,
  onChange,
  disabled,
  className,
}: {
  label: string;
  checked: boolean;
  onChange: ChangeEventHandler<HTMLInputElement>;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <label className={cn(
      "flex min-h-11 cursor-pointer items-center gap-2 rounded-xl border border-athar-line px-3 text-sm text-athar-ink-soft transition-colors has-checked:border-athar-accent/40 has-checked:bg-athar-accent/5 has-checked:text-athar-accent has-disabled:cursor-not-allowed has-disabled:opacity-45",
      className,
    )}>
      <input
        className="accent-athar-accent"
        type="checkbox"
        checked={checked}
        onChange={onChange}
        disabled={disabled}
      />
      <span>{label}</span>
    </label>
  );
}

export function StatTile({label, value, className}: {label: string; value: ReactNode; className?: string}) {
  return (
    <div className={cn("grid min-w-0 gap-0.5 rounded-xl border border-athar-line-soft bg-athar-line-soft px-3 py-2.5", className)}>
      <span className="text-[0.68rem] text-athar-ink-faint">{label}</span>
      <strong className="truncate text-sm text-athar-ink">{value}</strong>
    </div>
  );
}

export function ProgressBar({value, max, label, className}: {value: number; max: number; label: string; className?: string}) {
  const boundedMax = Math.max(1, max);
  const percentage = Math.max(0, Math.min(100, (value / boundedMax) * 100));
  return (
    <div className={cn("grid gap-1.5", className)} aria-label={label} role="progressbar" aria-valuemin={0} aria-valuemax={boundedMax} aria-valuenow={Math.max(0, Math.min(value, boundedMax))}>
      <div className="h-1.5 overflow-hidden rounded-full bg-athar-line">
        <span className="block h-full rounded-full bg-athar-accent transition-[width] duration-300" style={{width: `${percentage}%`}} />
      </div>
    </div>
  );
}

export function PlaybackTimeline({
  value,
  max,
  label,
  time,
  disabled,
  onChange,
  className,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "value" | "max" | "onChange"> & {
  value: number;
  max: number;
  label: string;
  time: ReactNode;
  disabled?: boolean;
  onChange: ChangeEventHandler<HTMLInputElement>;
}) {
  return (
    <div className={cn("grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 text-[0.7rem] tabular-nums text-athar-ink-faint max-[520px]:grid-cols-1", className)}>
      <input
        className="w-full accent-athar-accent"
        type="range"
        value={value}
        max={max}
        disabled={disabled}
        aria-label={label}
        onChange={onChange}
        {...props}
      />
      <span>{time}</span>
    </div>
  );
}

export function HandoffSurface({children, action}: {children: ReactNode; action: ReactNode}) {
  return (
    <Surface variant="subtle" className="flex flex-col items-start justify-between gap-3 rounded-athar-md p-5 text-sm text-athar-ink-soft sm:flex-row sm:items-center">
      <span>{children}</span>
      <div className="flex shrink-0 flex-wrap gap-4 font-bold text-athar-accent">{action}</div>
    </Surface>
  );
}

export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  className,
  variant = "bar",
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{value: T; label: string}>;
  onChange: (value: T) => void;
  className?: string;
  variant?: "bar" | "pills";
}) {
  const pills = variant === "pills";
  return (
    <div
      className={cn(
        "flex items-center",
        pills
          ? "gap-1 rounded-full border border-athar-line bg-athar-canvas-strong p-0.5"
          : "min-h-11 rounded-xl border border-athar-line bg-athar-canvas-strong p-1",
        className,
      )}
      role="group"
      aria-label={label}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            type="button"
            className={cn(
              "cursor-pointer font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-athar-accent",
              pills
                ? "rounded-full px-3.5 py-1.5 text-[0.8rem] text-athar-ink-soft hover:text-athar-ink"
                : "min-h-9 flex-1 rounded-[9px] px-3 text-sm text-athar-ink-soft",
              active && (pills
                ? "bg-athar-accent text-athar-on-accent shadow-athar-sm hover:text-athar-on-accent"
                : "bg-athar-surface text-athar-accent shadow-sm"),
            )}
            key={option.value}
            aria-pressed={active}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  className,
  density = "editorial",
}: {
  eyebrow: string;
  title: string;
  description: string;
  className?: string;
  density?: "editorial" | "compact" | "utility";
}) {
  const compact = density === "compact";
  const utility = density === "utility";
  return (
    <header className={cn(
      utility ? "mb-4 max-w-[820px]" : compact ? "mb-5 max-w-[820px] md:mb-6" : "mb-8 max-w-[920px] md:mb-10",
      className,
    )}>
      <p className={cn("font-bold tracking-[0.08em] text-athar-gold", utility ? "mb-0 text-[0.65rem]" : compact ? "mb-1 text-[0.7rem]" : "mb-2 text-xs")}>{eyebrow}</p>
      <h1 className={cn(
        "m-0 font-athar-display tracking-[-0.035em] text-athar-ink",
        utility
          ? "max-w-[720px] text-[clamp(2.15rem,4.2vw,3.5rem)] leading-none"
          : compact
          ? "max-w-[780px] text-[clamp(2.45rem,5.6vw,4.5rem)] leading-[1.02]"
          : "max-w-[900px] text-[clamp(2.5rem,7vw,5.25rem)] leading-[1.04]",
      )}>
        {title}
      </h1>
      <p className={cn(
        "max-w-[700px] text-athar-ink-soft",
        utility ? "mt-1.5 text-xs leading-5" : compact ? "mt-2 text-xs leading-6 sm:text-sm" : "mt-4 text-sm leading-7 sm:text-base",
      )}>{description}</p>
    </header>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  action,
  id,
  className,
}: {
  eyebrow: string;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <header className={cn("mb-5 flex flex-col items-start justify-between gap-4 sm:flex-row", className)}>
      <div className="grid gap-1">
        <span className="text-[0.7rem] font-bold text-athar-gold">{eyebrow}</span>
        <h2 id={id} className="m-0 font-athar-display text-[clamp(1.8rem,4vw,3rem)] leading-tight text-athar-ink">{title}</h2>
      </div>
      {action || description ? (
        <div className="max-w-[390px] text-xs leading-6 text-athar-ink-faint">{action || description}</div>
      ) : null}
    </header>
  );
}

type StatusTone = "neutral" | "loading" | "error";
const statusTones: Record<StatusTone, string> = {
  neutral: "border-athar-line-soft bg-athar-line-soft text-athar-ink-soft",
  loading: "border-athar-line-soft bg-athar-line-soft text-athar-ink-soft",
  error: "border-red-700/25 bg-red-700/8 text-red-800",
};

export function StatusState({
  tone = "neutral",
  children,
  action,
  className,
}: {
  tone?: StatusTone;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn("flex min-h-12 items-center justify-between gap-4 rounded-xl border px-4 py-3 text-sm", statusTones[tone], className)}
      role={tone === "error" ? "alert" : "status"}
    >
      <span>{children}</span>
      {action}
    </div>
  );
}

export function DrawerSurface({
  open,
  onClose,
  eyebrow,
  title,
  children,
  id,
}: {
  open: boolean;
  onClose: () => void;
  eyebrow?: string;
  title: string;
  children: ReactNode;
  id?: string;
}) {
  const generatedId = useId();
  const drawerId = id || generatedId;
  const titleId = `${drawerId}-title`;
  const onCloseRef = useRef(onClose);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const drawer = document.getElementById(drawerId);
    const frame = window.requestAnimationFrame(() => {
      drawer?.querySelector<HTMLElement>("[data-drawer-close]")?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !window.matchMedia("(max-width: 767px)").matches || !drawer) return;
      const focusable = [...drawer.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )].filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      previousFocusRef.current?.focus();
      previousFocusRef.current = null;
    };
  }, [drawerId, open]);

  if (!open) return null;
  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-[58] cursor-default border-0 bg-black/30 backdrop-blur-[2px] md:hidden"
        aria-label={`إغلاق ${title}`}
        onClick={onClose}
      />
      <Surface
        as="section"
        id={drawerId}
        className="fixed inset-x-0 bottom-0 z-[60] max-h-[82dvh] overflow-y-auto rounded-t-[26px] p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))] md:static md:mt-3 md:max-h-none md:overflow-visible md:rounded-athar-md md:p-5"
        role="dialog"
        aria-labelledby={titleId}
      >
        <header className="sticky top-0 z-10 mb-4 flex items-start justify-between gap-5 bg-athar-surface pb-3 md:static md:bg-transparent md:pb-0">
          <div className="grid gap-1">
            {eyebrow ? <span className="text-[0.7rem] font-bold text-athar-gold">{eyebrow}</span> : null}
            <h2 id={titleId} className="m-0 font-athar-display text-[clamp(1.8rem,4vw,2.5rem)] leading-tight text-athar-ink">{title}</h2>
          </div>
          <IconButton data-drawer-close label={`إغلاق ${title}`} className="size-9 text-xl" onClick={onClose}>×</IconButton>
        </header>
        {children}
      </Surface>
    </>
  );
}
