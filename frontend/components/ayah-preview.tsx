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
    <article className="ayah-preview" aria-labelledby="preview-title">
      <header className="mushaf-head">
        <span>الجزء الثالث</span>
        <span id="preview-title">سورة البقرة</span>
      </header>
      <div className="ayah-preview-body" aria-live="polite">
        {ayah ? (
          <p className="quran-text">{ayah.text}</p>
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
