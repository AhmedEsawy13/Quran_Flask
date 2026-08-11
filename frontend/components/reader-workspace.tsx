"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { type Ayah, type MushafPage, type Surah, getJson } from "@/lib/api";
import {
  MUSHAF_EDITIONS,
  isMushafEdition,
  isReaderView,
  toArabicDigits,
  type MushafEditionId,
  type ReaderView,
} from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { MushafRenderer } from "@/components/mushaf-renderer";
import { ReaderAudio } from "@/components/reader-audio";
import { ReaderStudy } from "@/components/reader-study";
import { Button, Field, HandoffSurface, SegmentedControl, SelectControl, StatusState, Surface } from "@/components/ui/primitives";
import { useEditionFont } from "@/lib/use-edition-font";

type ContentResult = {
  requestKey: string;
  ayah: Ayah | null;
  page: MushafPage | null;
  error: string;
};

function clampInteger(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, Math.trunc(value)));
}

function parsePositiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

export function ReaderWorkspace() {
  const searchParams = useSearchParams();
  const restoreLastPosition = !searchParams.has("surah") && !searchParams.has("ayah");
  const [positionReady, setPositionReady] = useState(!restoreLastPosition);
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [ayahNumbers, setAyahNumbers] = useState<number[]>([]);
  const ayahCache = useRef(new Map<number, number[]>());
  const [surahNumber, setSurahNumber] = useState(() =>
    clampInteger(parsePositiveInteger(searchParams.get("surah"), 2), 1, 114),
  );
  const [ayahNumber, setAyahNumber] = useState(() =>
    parsePositiveInteger(searchParams.get("ayah"), 255),
  );
  const [view, setView] = useState<ReaderView>(() => {
    const value = searchParams.get("view");
    return isReaderView(value) ? value : "page";
  });
  const [editionId, setEditionId] = useState<MushafEditionId>(() => {
    const value = searchParams.get("edition");
    return isMushafEdition(value) ? value : "digital_khatt";
  });
  const [catalogError, setCatalogError] = useState("");
  const [contentResult, setContentResult] = useState<ContentResult>({
    requestKey: "",
    ayah: null,
    page: null,
    error: "",
  });
  const [retryToken, setRetryToken] = useState(0);
  const [moving, setMoving] = useState(false);
  const [activeAudioWord, setActiveAudioWord] = useState<number | null>(null);
  const fontLoading = useEditionFont(editionId);
  const requestKey = `${view}:${editionId}:${surahNumber}:${ayahNumber}:${retryToken}`;
  const visibleResult = contentResult.requestKey === requestKey ? contentResult : null;
  const isContentLoading = positionReady && visibleResult === null;

  useEffect(() => {
    if (!restoreLastPosition) return;
    const frame = window.requestAnimationFrame(() => {
      const saved = window.localStorage.getItem("athar-reader-position");
      if (saved) {
        const [savedSurah, savedAyah] = saved.split(":").map(Number);
        if (
          Number.isInteger(savedSurah) && Number.isInteger(savedAyah) &&
          savedSurah >= 1 && savedSurah <= 114 && savedAyah >= 1
        ) {
          setSurahNumber(savedSurah);
          setAyahNumber(savedAyah);
        }
      }
      setPositionReady(true);
    });
    return () => window.cancelAnimationFrame(frame);
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
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تحميل قائمة السور.");
      });
    return () => controller.abort();
  }, [retryToken]);

  const loadAyahNumbers = useCallback(async (surah: number, signal?: AbortSignal) => {
    const cached = ayahCache.current.get(surah);
    if (cached) return cached;
    const numbers = await getJson<number[]>(`/backend-api/surahs/${surah}/ayahs`, signal);
    ayahCache.current.set(surah, numbers);
    return numbers;
  }, []);

  useEffect(() => {
    if (!positionReady) return;
    const controller = new AbortController();
    loadAyahNumbers(surahNumber, controller.signal)
      .then((numbers) => {
        setAyahNumbers(numbers);
        setCatalogError("");
        setAyahNumber((current) => {
          if (!numbers.length || numbers.includes(current)) return current;
          return current > numbers.length ? numbers[numbers.length - 1] : numbers[0];
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAyahNumbers([]);
        setCatalogError(reason instanceof Error ? reason.message : "تعذّر تحميل آيات السورة.");
      });
    return () => controller.abort();
  }, [surahNumber, positionReady, retryToken, loadAyahNumbers]);

  useEffect(() => {
    if (!positionReady) return;
    const controller = new AbortController();
    const edition = MUSHAF_EDITIONS[editionId];
    const path = view === "page"
      ? `/backend-api/${edition.apiBase}/page-by-ayah/${surahNumber}/${ayahNumber}`
      : `/backend-api/surahs/${surahNumber}/ayahs/${ayahNumber}?source=qpc_hafs`;
    getJson<Ayah | MushafPage>(path, controller.signal)
      .then((data) => {
        setContentResult({
          requestKey,
          ayah: view === "verse" ? data as Ayah : null,
          page: view === "page" ? data as MushafPage : null,
          error: "",
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setContentResult({
          requestKey,
          ayah: null,
          page: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل المصحف.",
        });
      });
    return () => controller.abort();
  }, [positionReady, view, editionId, surahNumber, ayahNumber, retryToken, requestKey]);

  useEffect(() => {
    if (!positionReady) return;
    const url = new URL(window.location.href);
    url.searchParams.set("surah", String(surahNumber));
    url.searchParams.set("ayah", String(ayahNumber));
    url.searchParams.set("view", view);
    url.searchParams.set("edition", editionId);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    window.localStorage.setItem("athar-reader-position", `${surahNumber}:${ayahNumber}`);
  }, [positionReady, surahNumber, ayahNumber, view, editionId]);

  const selectedSurah = useMemo(
    () => surahs.find((surah) => surah.number === surahNumber),
    [surahs, surahNumber],
  );
  const currentIndex = ayahNumbers.indexOf(ayahNumber);
  const atFirstAyah = surahNumber === 1 && ayahNumber === 1;
  const atLastAyah = surahNumber === 114 && currentIndex === ayahNumbers.length - 1;

  const retry = useCallback(() => {
    setCatalogError("");
    ayahCache.current.delete(surahNumber);
    setRetryToken((value) => value + 1);
  }, [surahNumber]);

  const navigateToVerse = useCallback((surah: number, ayah: number) => {
    setCatalogError("");
    setSurahNumber(clampInteger(surah, 1, 114));
    setAyahNumber(Math.max(1, Math.trunc(ayah)));
  }, []);

  const move = useCallback(async (direction: -1 | 1) => {
    if (moving) return;
    setMoving(true);
    try {
      if (direction > 0) {
        if (currentIndex >= 0 && currentIndex < ayahNumbers.length - 1) {
          setAyahNumber(ayahNumbers[currentIndex + 1]);
        } else if (surahNumber < 114) {
          setSurahNumber(surahNumber + 1);
          setAyahNumber(1);
        }
      } else if (currentIndex > 0) {
        setAyahNumber(ayahNumbers[currentIndex - 1]);
      } else if (surahNumber > 1) {
        const previousSurah = surahNumber - 1;
        const previousNumbers = await loadAyahNumbers(previousSurah);
        setSurahNumber(previousSurah);
        setAyahNumber(previousNumbers.at(-1) || 1);
      }
    } catch (reason: unknown) {
      setCatalogError(reason instanceof Error ? reason.message : "تعذّر الانتقال بين الآيات.");
    } finally {
      setMoving(false);
    }
  }, [moving, currentIndex, ayahNumbers, surahNumber, loadAyahNumbers]);
  const advanceAfterAudio = useCallback(() => move(1), [move]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
        target?.isContentEditable || ["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target?.tagName || "")
      ) return;
      if (event.key === "ArrowLeft" && !atLastAyah) {
        event.preventDefault();
        void move(1);
      } else if (event.key === "ArrowRight" && !atFirstAyah) {
        event.preventDefault();
        void move(-1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [move, atFirstAyah, atLastAyah]);

  return (
    <section className="grid gap-3.5 sm:gap-4" aria-label="قارئ المصحف">
      <Surface
        variant="toolbar"
        className="grid grid-cols-2 items-end gap-2 rounded-athar-md p-3 sm:grid-cols-4 md:sticky md:top-[calc(var(--bar-height)+.5rem)] md:z-20 lg:grid-cols-[auto_minmax(150px,1fr)_minmax(92px,.45fr)_minmax(165px,1fr)_auto] lg:gap-3 lg:p-3.5"
      >
        <SegmentedControl
          label="طريقة العرض"
          value={view}
          options={[{value: "page", label: "صفحة"}, {value: "verse", label: "آية"}]}
          onChange={setView}
          className="col-span-2 sm:col-span-1"
        />
        <Field label="السورة" className="col-span-2 sm:col-span-2 lg:col-span-1">
          <SelectControl
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
                {toArabicDigits(surah.number)}. {surah.name}
              </option>
            ))}
          </SelectControl>
        </Field>
        <Field label="الآية">
          <SelectControl
            value={ayahNumber}
            onChange={(event) => setAyahNumber(Number(event.target.value))}
            disabled={!ayahNumbers.length}
          >
            {!ayahNumbers.length ? <option>{toArabicDigits(ayahNumber)}</option> : null}
            {ayahNumbers.map((number) => <option key={number} value={number}>{toArabicDigits(number)}</option>)}
          </SelectControl>
        </Field>
        <Field label="طبعة المصحف">
          <SelectControl value={editionId} onChange={(event) => setEditionId(event.target.value as MushafEditionId)}>
            {Object.values(MUSHAF_EDITIONS).map((edition) => (
              <option key={edition.id} value={edition.id}>{edition.label}</option>
            ))}
          </SelectControl>
        </Field>
        <div className="col-span-2 flex gap-2 sm:col-span-4 lg:col-span-1" aria-label="التنقل بين الآيات">
          <Button className="flex-1" variant="quiet" onClick={() => void move(-1)} disabled={moving || !ayahNumbers.length || atFirstAyah} aria-label="الآية السابقة">
            السابق
          </Button>
          <Button className="flex-1" onClick={() => void move(1)} disabled={moving || !ayahNumbers.length || atLastAyah} aria-label="الآية التالية">
            التالي
          </Button>
        </div>
      </Surface>

      <p className="-mt-2 me-1 hidden text-end text-[0.7rem] text-athar-ink-faint md:block">لوحة المفاتيح: ← للآية التالية، → للسابقة</p>

      {catalogError ? (
        <StatusState tone="error" action={<Button size="sm" variant="danger" onClick={retry}>أعد المحاولة</Button>}>
          {catalogError}
        </StatusState>
      ) : null}

      <ReaderAudio
        surahNumber={surahNumber}
        ayahNumber={ayahNumber}
        onAdvance={advanceAfterAudio}
        atLastAyah={atLastAyah}
        onWordChange={setActiveAudioWord}
      />

      <ReaderStudy
        surahNumber={surahNumber}
        ayahNumber={ayahNumber}
        initialAyah={visibleResult?.ayah || null}
        surahs={surahs}
        onNavigate={navigateToVerse}
      />

      <MushafRenderer
        view={view}
        editionId={editionId}
        ayah={visibleResult?.ayah || null}
        page={visibleResult?.page || null}
        surahs={surahs}
        selectedSurah={selectedSurah}
        surahNumber={surahNumber}
        ayahNumber={ayahNumber}
        isLoading={!positionReady || isContentLoading}
        error={visibleResult?.error || ""}
        fontLoading={fontLoading}
        activeAudioWord={activeAudioWord}
        onRetry={retry}
      />

      <HandoffSurface action={<a href={legacyUrl(`/read?surah=${surahNumber}&ayah=${ayahNumber}`)}>أدوات القراءة السابقة</a>}>
        تحتاج أداة غير منقولة بعد؟ النسخة السابقة تبقى متاحة أثناء الانتقال.
      </HandoffSurface>
    </section>
  );
}
