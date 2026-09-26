import {cn} from "@/lib/cn";
import type {ToolKey} from "@/lib/nav";

export type DoorKey = ToolKey | "search";

function DoorGlyph({name}: {name: DoorKey}) {
  if (name === "read") {
    return <path d="M4 5.5c2.9-.8 5.1-.25 8 1.5 2.9-1.75 5.1-2.3 8-1.5v13c-2.9-.8-5.1-.25-8 1.5-2.9-1.75-5.1-2.3-8-1.5v-13Zm8 1.5v13" />;
  }
  if (name === "memorize") {
    return <path d="M6.2 7.2A7.5 7.5 0 0 1 19 10h2.2L18 13.2 14.8 10H17a5.5 5.5 0 0 0-9.35-1.55M17.8 16.8A7.5 7.5 0 0 1 5 14H2.8L6 10.8 9.2 14H7a5.5 5.5 0 0 0 9.35 1.55" />;
  }
  if (name === "waqf") {
    return <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-2.3-12v6m4.6-6v6" />;
  }
  if (name === "lab") {
    // Lines of text under a lens: searching across the whole Quran.
    return <path d="M4 6h8M4 10h5M4 14h4M4 18h9m1.2-4.2a3.8 3.8 0 1 0 5.4-5.4 3.8 3.8 0 0 0-5.4 5.4Zm0 0L11.5 16.5" />;
  }
  if (name === "search") {
    return <path d="M10.8 17.6a6.8 6.8 0 1 0 0-13.6 6.8 6.8 0 0 0 0 13.6ZM15.6 15.6 20 20" />;
  }
  return <path d="M12 3v3m0 12v3M3 12h3m12 0h3m-6.2-4.8-5.6 9.6m0-9.6 5.6 9.6M12 9.2a2.8 2.8 0 1 0 0 5.6 2.8 2.8 0 0 0 0-5.6Z" />;
}

export function DoorIcon({name, className}: {name: DoorKey; className?: string}) {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" className={cn("size-5 fill-none stroke-current stroke-[1.7] [stroke-linecap:round] [stroke-linejoin:round]", className)}>
      <DoorGlyph name={name} />
    </svg>
  );
}

/** Brand mark: the أ of أثَر on the accent tile. */
export function AtharMark({className}: {className?: string}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "grid size-9 shrink-0 place-items-center rounded-[11px] bg-athar-accent pt-1 font-athar-display text-xl leading-none text-athar-on-accent shadow-[inset_0_-2px_0_color-mix(in_srgb,var(--athar-ink)_18%,transparent)]",
        className,
      )}
    >
      أ
    </span>
  );
}
