import {cn} from "@/lib/cn";

export const pageContainerClassName = "mx-auto w-full max-w-[1180px] px-3 sm:px-5";

type ActionLinkVariant = "primary" | "quiet";

const actionLinkVariants: Record<ActionLinkVariant, string> = {
  primary: "border-athar-accent bg-athar-accent text-athar-on-accent shadow-[0_10px_24px_color-mix(in_srgb,var(--athar-accent)_22%,transparent)] hover:bg-athar-accent-soft",
  quiet: "border-athar-line bg-athar-surface text-athar-ink hover:border-athar-accent hover:text-athar-accent",
};

export function actionLinkClassName(variant: ActionLinkVariant, className?: string) {
  return cn(
    "inline-flex min-h-12 items-center justify-center rounded-[13px] border px-[18px] py-2.5 font-bold no-underline transition-[background-color,border-color,color,box-shadow,transform] hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent",
    actionLinkVariants[variant],
    className,
  );
}

export function introLinkClassName(className?: string) {
  return cn(
    "border-b border-athar-accent/35 text-[0.88rem] font-bold text-athar-accent no-underline hover:border-athar-accent",
    className,
  );
}

export function pillActionClassName(className?: string) {
  return cn(
    "inline-flex items-center self-start rounded-full bg-athar-accent px-4 py-2 text-[0.88rem] font-bold text-athar-on-accent no-underline hover:brightness-95",
    className,
  );
}
