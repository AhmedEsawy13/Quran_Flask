"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { type Ayah, getJson } from "@/lib/api";

export function AyahPreview() {
  const [ayah, setAyah] = useState<Ayah | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getJson<Ayah>(
      "/backend-api/surahs/2/ayahs/255?source=qpc_hafs",
      controller.signal,
    )
      .then(setAyah)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(reason instanceof Error ? reason.message : "تعذّر تحميل الآية.");
      });
    return () => controller.abort();
  }, []);

  return (
    <article
      className="min-h-[590px] overflow-hidden rounded-[4px_18px_18px_4px] border border-athar-line bg-[linear-gradient(110deg,transparent_0_49.5%,var(--athar-line-soft)_50%,transparent_50.5%),var(--athar-surface)] shadow-athar-lg [transform:rotateY(-4deg)_rotateZ(.5deg)] max-[640px]:min-h-[480px] max-[640px]:transform-none"
      aria-labelledby="preview-title"
    >
      <header className="mushaf-head">
        <span>الجزء الثالث</span>
        <span id="preview-title">سورة البقرة</span>
      </header>
      <div className="grid min-h-[500px] place-items-center p-[clamp(34px,6vw,70px)] max-[640px]:min-h-[390px] max-[640px]:p-7" aria-live="polite">
        {ayah ? (
          <p className="quran-text text-[clamp(1.65rem,3vw,2.5rem)] max-[640px]:text-[1.55rem]">{ayah.text}</p>
        ) : error ? (
          <div className="inline-error">
            <strong>الخادم غير متاح الآن</strong>
            <span>{error}</span>
          </div>
        ) : (
          <div className="verse-skeleton" aria-label="جارٍ تحميل آية الكرسي">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>
      <footer className="mushaf-foot">
        <span>مصحف المدينة</span>
        <Link href="/read?surah=2&ayah=255">٢٥٥</Link>
      </footer>
    </article>
  );
}
