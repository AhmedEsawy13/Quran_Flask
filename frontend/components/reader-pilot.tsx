"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { type Ayah, type Surah, getJson } from "@/lib/api";
import { legacyUrl } from "@/lib/paths";

type AyahResult = {
  requestKey: string;
  data: Ayah | null;
  error: string;
};

function clampInteger(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, Math.trunc(value)));
}

function parsePositiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function ReaderPilot() {
  const searchParams = useSearchParams();
  const [restoreLastPosition] = useState(
    () => !searchParams.has("surah") && !searchParams.has("ayah"),
  );
  const [initialSurah] = useState(() =>
    parsePositiveInteger(searchParams.get("surah"), 2),
  );
  const [initialAyah] = useState(() =>
    parsePositiveInteger(searchParams.get("ayah"), 255),
  );
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const [surahNumber, setSurahNumber] = useState(() =>
    clampInteger(initialSurah, 1, 114),
  );
  const [ayahNumber, setAyahNumber] = useState(() => Math.max(1, initialAyah));
  const [catalogError, setCatalogError] = useState("");
  const [ayahResult, setAyahResult] = useState<AyahResult>({
    requestKey: "",
    data: null,
    error: "",
  });
  const [retryToken, setRetryToken] = useState(0);
  const requestKey = `${surahNumber}:${ayahNumber}:${retryToken}`;
  const visibleResult = ayahResult.requestKey === requestKey ? ayahResult : null;
  const isAyahLoading = visibleResult === null;

  useEffect(() => {
    if (!restoreLastPosition) return;
    const saved = window.localStorage.getItem("athar-reader-position");
    if (!saved) return;
    const [savedSurah, savedAyah] = saved.split(":").map(Number);
    if (
      Number.isInteger(savedSurah) &&
      Number.isInteger(savedAyah) &&
      savedSurah >= 1 &&
      savedSurah <= 114 &&
      savedAyah >= 1
    ) {
      const frame = window.requestAnimationFrame(() => {
        setSurahNumber(savedSurah);
        setAyahNumber(savedAyah);
      });
      return () => window.cancelAnimationFrame(frame);
    }
  }, [restoreLastPosition]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Surah[]>("/backend-api/surahs", controller.signal)
      .then((items) => {
        setSurahs(items);
        setCatalogError("");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setCatalogError(
          reason instanceof Error ? reason.message : "تعذّر تحميل قائمة السور.",
        );
      });
    return () => controller.abort();
  }, [retryToken]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<number[]>(
      `/backend-api/surahs/${surahNumber}/ayahs`,
      controller.signal,
    )
      .then((numbers) => {
        setAyahNumbers(numbers);
        setCatalogError("");
        setAyahNumber((current) =>
          numbers.length && !numbers.includes(current) ? numbers[0] : current,
        );
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAyahNumbers([]);
        setCatalogError(
          reason instanceof Error ? reason.message : "تعذّر تحميل آيات السورة.",
        );
      });
    return () => controller.abort();
  }, [surahNumber, retryToken]);

  useEffect(() => {
    const controller = new AbortController();
    getJson<Ayah>(
      `/backend-api/surahs/${surahNumber}/ayahs/${ayahNumber}?source=qpc_hafs`,
      controller.signal,
    )
      .then((data) => {
        setAyahResult({ requestKey, data, error: "" });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAyahResult({
          requestKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل الآية.",
        });
      });
    return () => controller.abort();
  }, [surahNumber, ayahNumber, retryToken, requestKey]);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("ayah", String(ayahNumber));
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
    window.localStorage.setItem(
      "athar-reader-position",
      `${surahNumber}:${ayahNumber}`,
    );
  }, [surahNumber, ayahNumber]);

  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const currentIndex = ayahNumbers.indexOf(ayahNumber);

  const retry = useCallback(() => {
    setCatalogError("");
    setRetryToken((value) => value + 1);
  }, []);

  const move = useCallback(
    (direction: -1 | 1) => {
      const nextIndex = currentIndex + direction;
      if (nextIndex >= 0 && nextIndex < ayahNumbers.length) {
        setAyahNumber(ayahNumbers[nextIndex]);
      }
    },
    [ayahNumbers, currentIndex],
  );

  return (
    <section className="reader-workspace" aria-label="قارئ تجريبي">
      <div className="reader-toolbar">
        <label>
          <span>السورة</span>
          <select
            value={surahNumber}
            onChange={(event) => {
              setCatalogError("");
              setSurahNumber(Number(event.target.value));
              setAyahNumber(1);
            }}
            disabled={!surahs.length}
          >
            {!surahs.length ? <option>جارٍ التحميل…</option> : null}
            {surahs.map((surah) => (
              <option key={surah.number} value={surah.number}>
                {surah.number}. {surah.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>الآية</span>
          <select
            value={ayahNumber}
            onChange={(event) => setAyahNumber(Number(event.target.value))}
            disabled={!ayahNumbers.length}
          >
            {!ayahNumbers.length ? <option>{ayahNumber}</option> : null}
            {ayahNumbers.map((number) => (
              <option key={number} value={number}>
                {number}
              </option>
            ))}
          </select>
        </label>
        <div className="reader-stepper" aria-label="التنقل بين الآيات">
          <button
            type="button"
            onClick={() => move(-1)}
            disabled={currentIndex <= 0}
            aria-label="الآية السابقة"
          >
            السابق
          </button>
          <button
            type="button"
            onClick={() => move(1)}
            disabled={currentIndex < 0 || currentIndex >= ayahNumbers.length - 1}
            aria-label="الآية التالية"
          >
            التالي
          </button>
        </div>
      </div>

      {catalogError ? (
        <div className="reader-alert" role="alert">
          <span>{catalogError}</span>
          <button type="button" onClick={retry}>
            أعد المحاولة
          </button>
        </div>
      ) : null}

      <article className="reader-page" aria-busy={isAyahLoading}>
        <header className="mushaf-head">
          <span>قراءة تجريبية</span>
          <span>{selectedSurah ? `سورة ${selectedSurah.name}` : "المصحف"}</span>
        </header>
        <div className="reader-page-body" aria-live="polite">
          {isAyahLoading ? (
            <div className="verse-skeleton reader-skeleton" aria-label="جارٍ تحميل الآية">
              <span />
              <span />
              <span />
            </div>
          ) : visibleResult.error ? (
            <div className="inline-error">
              <strong>لم تصل الآية</strong>
              <span>{visibleResult.error}</span>
              <button type="button" onClick={retry}>
                أعد المحاولة
              </button>
            </div>
          ) : visibleResult.data ? (
            <>
              <p className="quran-text reader-verse">{visibleResult.data.text}</p>
              {visibleResult.data.transliteration?.t ? (
                <details className="transliteration">
                  <summary>النقل الصوتي</summary>
                  <p dir="ltr">{visibleResult.data.transliteration.t}</p>
                </details>
              ) : null}
            </>
          ) : null}
        </div>
        <footer className="mushaf-foot">
          <span>الرسم العثماني — حفص</span>
          <span className="page-number">{ayahNumber}</span>
        </footer>
      </article>

      <div className="pilot-note">
        <div>
          <strong>هذا مسار قياس، لا بديل المصحف الكامل بعد.</strong>
          <p>الواجهة تظهر فورًا، ثم يصل نص الآية من خادم Heroku الحالي.</p>
        </div>
        <a href={legacyUrl(`/read?surah=${surahNumber}&ayah=${ayahNumber}`)}>
          افتح المصحف الحالي
        </a>
      </div>
    </section>
  );
}
