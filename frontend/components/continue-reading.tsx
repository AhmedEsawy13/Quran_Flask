"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getJson, type Surah } from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";
import { DoorIcon } from "@/components/ui/door-icon";
import { readStorage } from "@/lib/storage";

type Position = {surah: number; ayah: number; name: string};

function savedPosition() {
  const [surah, ayah] = (readStorage("athar-reader-position") || "").split(":").map(Number);
  return Number.isInteger(surah) && Number.isInteger(ayah) && surah >= 1 && surah <= 114 && ayah >= 1
    ? {surah, ayah}
    : null;
}

/** Returning readers get one tap back to where the reader last left them. */
export function ContinueReading() {
  const [position, setPosition] = useState<Position | null>(null);

  useEffect(() => {
    const saved = savedPosition();
    if (!saved) return;
    const controller = new AbortController();
    const fallback = `سورة ${toArabicDigits(saved.surah)}`;
    getJson<Surah[]>("/backend-api/surahs", controller.signal)
      .then((surahs) => setPosition({...saved, name: surahs.find((item) => item.number === saved.surah)?.name || fallback}))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setPosition({...saved, name: fallback});
      });
    return () => controller.abort();
  }, []);

  if (!position) return null;
  return (
    <Link
      href={`/read?surah=${position.surah}&ayah=${position.ayah}`}
      className="group mt-6 flex w-full max-w-[460px] items-center gap-3 rounded-2xl border border-athar-line bg-athar-surface p-3 pe-4 no-underline shadow-athar-sm transition-[border-color,transform] hover:-translate-y-0.5 hover:border-athar-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent"
    >
      <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-athar-accent/12 text-athar-accent">
        <DoorIcon name="read" />
      </span>
      <span className="grid min-w-0 flex-1 gap-0.5">
        <span className="text-[0.72rem] font-semibold text-athar-ink-faint">تابع من حيث توقفت</span>
        <strong className="truncate text-athar-ink">{position.name} · الآية {toArabicDigits(position.ayah)}</strong>
      </span>
      <span aria-hidden="true" className="text-lg text-athar-accent transition-transform group-hover:-translate-x-1">←</span>
    </Link>
  );
}
