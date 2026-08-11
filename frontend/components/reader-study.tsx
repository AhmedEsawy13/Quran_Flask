"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getJson,
  getJsonAccepting,
  type AsbabPayload,
  type Ayah,
  type MutashabihatMatch,
  type MutashabihatPayload,
  type Surah,
  type TafseerCollection,
} from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";
import { legacyUrl } from "@/lib/paths";
import { Button, DrawerSurface, Field, SelectControl, StatusState } from "@/components/ui/primitives";

type StudyTool = "meanings" | "tafseer" | "mutashabihat" | "asbab" | "transliteration" | "study";

type ReaderStudyProps = {
  surahNumber: number;
  ayahNumber: number;
  initialAyah: Ayah | null;
  surahs: Surah[];
  onNavigate: (surah: number, ayah: number) => void;
};

type VerseResult = {
  key: string;
  data: Ayah | null;
  error: string;
};

type TafseerResult = {
  key: string;
  data: Record<string, string> | null;
  error: string;
};

type MutashabihatResult = {
  key: string;
  data: MutashabihatPayload | null;
  error: string;
};

type AsbabResult = {
  key: string;
  data: AsbabPayload | null;
  error: string;
};

const verseCache = new Map<string, Ayah>();
const tafseerCache = new Map<string, Record<string, string>>();
const mutashabihatCache = new Map<string, MutashabihatPayload>();
const asbabCache = new Map<string, AsbabPayload>();

const tools: Array<{id: StudyTool; label: string}> = [
  {id: "meanings", label: "معاني الكلمات"},
  {id: "tafseer", label: "التفسير"},
  {id: "mutashabihat", label: "المتشابهات"},
  {id: "asbab", label: "سبب النزول"},
  {id: "transliteration", label: "النطق الحرفي"},
  {id: "study", label: "أدوات الدراسة"},
];

function plainTextFromHtml(html: string) {
  const template = document.createElement("template");
  template.innerHTML = html;
  template.content.querySelectorAll("script, style").forEach((element) => element.remove());
  return (template.content.textContent || "").replace(/\s+/g, " ").trim();
}

function differingWordIndexes(match: MutashabihatMatch) {
  const indexes = new Set<number>();
  match.opcodes.forEach(([tag, , , from, to]) => {
    if (tag === "equal") return;
    for (let index = from; index < to; index += 1) indexes.add(index);
  });
  return indexes;
}

function runLabel(count: number) {
  if (count === 2) return "كلمتان متتاليتان";
  if (count >= 3 && count <= 10) return `${toArabicDigits(count)} كلمات متتالية`;
  return `${toArabicDigits(count)} كلمة متتالية`;
}

export function ReaderStudy({
  surahNumber,
  ayahNumber,
  initialAyah,
  surahs,
  onNavigate,
}: ReaderStudyProps) {
  const [activeTool, setActiveTool] = useState<StudyTool | null>(null);
  const [verseResult, setVerseResult] = useState<VerseResult>({key: "", data: null, error: ""});
  const [tafseerResult, setTafseerResult] = useState<TafseerResult>({key: "", data: null, error: ""});
  const [mutashabihatResult, setMutashabihatResult] = useState<MutashabihatResult>({key: "", data: null, error: ""});
  const [asbabResult, setAsbabResult] = useState<AsbabResult>({key: "", data: null, error: ""});
  const [selectedTafseer, setSelectedTafseer] = useState("");
  const verseKey = `${surahNumber}:${ayahNumber}`;
  const ayahData = initialAyah?.verse_key === verseKey
    ? initialAyah
    : verseResult.key === verseKey ? verseResult.data : null;
  const verseError = verseResult.key === verseKey ? verseResult.error : "";
  const tafseers = tafseerResult.key === verseKey ? tafseerResult.data : null;
  const tafseerError = tafseerResult.key === verseKey ? tafseerResult.error : "";
  const mutashabihat = mutashabihatResult.key === verseKey ? mutashabihatResult.data : null;
  const mutashabihatError = mutashabihatResult.key === verseKey ? mutashabihatResult.error : "";
  const asbab = asbabResult.key === verseKey ? asbabResult.data : null;
  const asbabError = asbabResult.key === verseKey ? asbabResult.error : "";
  const needsAyah = activeTool === "meanings" || activeTool === "transliteration";

  useEffect(() => {
    if (!needsAyah || ayahData) return;
    const cached = verseCache.get(verseKey);
    if (cached) {
      queueMicrotask(() => setVerseResult({key: verseKey, data: cached, error: ""}));
      return;
    }
    const controller = new AbortController();
    getJson<Ayah>(
      `/backend-api/surahs/${surahNumber}/ayahs/${ayahNumber}?source=qpc_hafs`,
      controller.signal,
    )
      .then((data) => {
        verseCache.set(verseKey, data);
        setVerseResult({key: verseKey, data, error: ""});
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setVerseResult({
          key: verseKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل بيانات الآية.",
        });
      });
    return () => controller.abort();
  }, [needsAyah, ayahData, verseKey, surahNumber, ayahNumber]);

  useEffect(() => {
    if (activeTool !== "tafseer" || tafseers) return;
    const cached = tafseerCache.get(verseKey);
    if (cached) {
      queueMicrotask(() => {
        setTafseerResult({key: verseKey, data: cached, error: ""});
        const remembered = window.localStorage.getItem("athar-reader-tafseer") || "";
        setSelectedTafseer(remembered in cached ? remembered : Object.keys(cached)[0] || "");
      });
      return;
    }
    const controller = new AbortController();
    getJson<TafseerCollection>(`/backend-api/tafseer/${surahNumber}/${ayahNumber}`, controller.signal)
      .then((collection) => {
        const normalized = Object.fromEntries(
          Object.entries(collection).map(([name, entry]) => [name, plainTextFromHtml(entry.text)]),
        );
        tafseerCache.set(verseKey, normalized);
        setTafseerResult({key: verseKey, data: normalized, error: ""});
        const remembered = window.localStorage.getItem("athar-reader-tafseer") || "";
        setSelectedTafseer(remembered in normalized ? remembered : Object.keys(normalized)[0] || "");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setTafseerResult({
          key: verseKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل التفسير.",
        });
      });
    return () => controller.abort();
  }, [activeTool, tafseers, verseKey, surahNumber, ayahNumber]);

  useEffect(() => {
    if (activeTool !== "mutashabihat" || mutashabihat) return;
    const cached = mutashabihatCache.get(verseKey);
    if (cached) {
      queueMicrotask(() => setMutashabihatResult({key: verseKey, data: cached, error: ""}));
      return;
    }
    const controller = new AbortController();
    getJson<MutashabihatPayload>(
      `/backend-api/mutashabihat/${surahNumber}/${ayahNumber}`,
      controller.signal,
    )
      .then((data) => {
        mutashabihatCache.set(verseKey, data);
        setMutashabihatResult({key: verseKey, data, error: ""});
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setMutashabihatResult({
          key: verseKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل المتشابهات.",
        });
      });
    return () => controller.abort();
  }, [activeTool, mutashabihat, verseKey, surahNumber, ayahNumber]);

  useEffect(() => {
    if (activeTool !== "asbab" || asbab) return;
    const cached = asbabCache.get(verseKey);
    if (cached) {
      queueMicrotask(() => setAsbabResult({key: verseKey, data: cached, error: ""}));
      return;
    }
    const controller = new AbortController();
    getJsonAccepting<AsbabPayload>(
      `/backend-api/asbab/${surahNumber}/${ayahNumber}`,
      [404],
      controller.signal,
    )
      .then((data) => {
        asbabCache.set(verseKey, data);
        setAsbabResult({key: verseKey, data, error: ""});
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setAsbabResult({
          key: verseKey,
          data: null,
          error: reason instanceof Error ? reason.message : "تعذّر تحميل سبب النزول.",
        });
      });
    return () => controller.abort();
  }, [activeTool, asbab, verseKey, surahNumber, ayahNumber]);

  const activeLabel = tools.find((tool) => tool.id === activeTool)?.label || "";
  const tafseerText = useMemo(
    () => selectedTafseer && tafseers ? tafseers[selectedTafseer] : "",
    [selectedTafseer, tafseers],
  );

  return (
    <section className="mx-auto w-full max-w-[790px]" aria-label="أدوات فهم الآية">
      <div className="grid grid-cols-2 gap-1.5 rounded-[15px] border border-athar-line bg-[color-mix(in_srgb,var(--athar-surface)_82%,transparent)] p-1.5 sm:grid-cols-3 lg:grid-cols-6">
        {tools.map((tool) => (
          <Button
            key={tool.id}
            size="sm"
            variant={activeTool === tool.id ? "primary" : "ghost"}
            className="w-full px-2"
            aria-expanded={activeTool === tool.id}
            aria-controls={activeTool === tool.id ? "reader-study-drawer" : undefined}
            onClick={() => setActiveTool((current) => current === tool.id ? null : tool.id)}
          >
            {tool.label}
          </Button>
        ))}
      </div>

      {activeTool ? (
        <DrawerSurface
          open
          id="reader-study-drawer"
          eyebrow={`الآية ${toArabicDigits(surahNumber)}:${toArabicDigits(ayahNumber)}`}
          title={activeLabel}
          onClose={() => setActiveTool(null)}
        >
          {needsAyah && !ayahData && !verseError ? <StatusState tone="loading">جارٍ تحميل بيانات الآية…</StatusState> : null}
          {verseError ? <StatusState tone="error">{verseError}</StatusState> : null}

          {activeTool === "meanings" && ayahData ? (
            <div>
              {ayahData.word_meanings_source?.attribution ? (
                <p className="mb-2 mt-4 text-[0.7rem] text-athar-ink-faint">المصدر: {ayahData.word_meanings_source.attribution}</p>
              ) : null}
              {ayahData.word_meanings_ordered?.length ? (
                <dl className="mt-4 grid gap-2 md:grid-cols-2">
                  {ayahData.word_meanings_ordered.map((entry, index) => (
                    <div className="grid grid-cols-[85px_minmax(0,1fr)] gap-2.5 rounded-xl border border-athar-line-soft p-3 sm:grid-cols-[minmax(90px,.35fr)_minmax(0,1fr)]" key={`${entry.word_no}-${entry.word}-${index}`}>
                      <dt className="font-athar-quran text-lg text-athar-accent">{entry.word}</dt>
                      <dd className="m-0 text-sm text-athar-ink-soft">{entry.meaning}</dd>
                    </div>
                  ))}
                </dl>
              ) : <StatusState className="justify-center">لا توجد معاني كلمات متاحة لهذه الآية.</StatusState>}
            </div>
          ) : null}

          {activeTool === "transliteration" && ayahData ? (
            ayahData.transliteration?.t
              ? <p className="mt-5 text-left font-sans leading-8 text-athar-ink-soft" dir="ltr">{ayahData.transliteration.t}</p>
              : <StatusState className="justify-center">لا يتوفر نقل حرفي لهذه الآية.</StatusState>
          ) : null}

          {activeTool === "tafseer" ? (
            <div className="mt-4 grid gap-4">
              {!tafseers && !tafseerError ? <StatusState tone="loading">جارٍ تحميل التفاسير المحلية…</StatusState> : null}
              {tafseerError ? <StatusState tone="error">{tafseerError}</StatusState> : null}
              {tafseers && Object.keys(tafseers).length ? (
                <>
                  <Field label="المصدر" className="w-full max-w-[330px]">
                    <SelectControl value={selectedTafseer} onChange={(event) => {
                      setSelectedTafseer(event.target.value);
                      window.localStorage.setItem("athar-reader-tafseer", event.target.value);
                    }}>
                      {Object.keys(tafseers).map((name) => <option key={name} value={name}>{name}</option>)}
                    </SelectControl>
                  </Field>
                  <p className="m-0 leading-8 text-athar-ink-soft">{tafseerText}</p>
                </>
              ) : tafseers ? <StatusState className="justify-center">لا يتوفر تفسير محلي لهذه الآية.</StatusState> : null}
            </div>
          ) : null}

          {activeTool === "mutashabihat" ? (
            <div className="mt-4">
              {!mutashabihat && !mutashabihatError ? <StatusState tone="loading">جارٍ البحث في المواضع المتشابهة…</StatusState> : null}
              {mutashabihatError ? <StatusState tone="error">{mutashabihatError}</StatusState> : null}
              {mutashabihat?.matches.length ? (
                <div className="grid max-h-[620px] gap-2 overflow-y-auto pe-1 [scrollbar-color:var(--athar-line)_transparent]">
                  {mutashabihat.matches.map((match) => {
                    const differing = differingWordIndexes(match);
                    const surahName = surahs.find((surah) => surah.number === match.surah)?.name || `سورة ${toArabicDigits(match.surah)}`;
                    return (
                      <button
                        type="button"
                        className="grid w-full cursor-pointer gap-3 rounded-[13px] border border-athar-line-soft bg-athar-canvas p-4 text-start text-athar-ink transition-colors hover:border-athar-accent"
                        key={match.verse_key}
                        onClick={() => {
                          onNavigate(match.surah, match.ayah);
                          setActiveTool(null);
                        }}
                        aria-label={`انتقل إلى سورة ${surahName} الآية ${toArabicDigits(match.ayah)}`}
                      >
                        <span className="flex items-center justify-between gap-3">
                          <strong className="text-athar-accent">{surahName} · {toArabicDigits(match.ayah)}</strong>
                          <small className="shrink-0 rounded-full bg-athar-gold/10 px-2 py-0.5 text-[0.7rem] text-athar-gold">{match.near_duplicate ? "شبه مطابقة" : runLabel(match.longest_run)}</small>
                        </span>
                        <span className="font-athar-quran text-xl leading-8" dir="rtl">
                          {match.words.map((word, index) => (
                            <span className={differing.has(index) ? "rounded bg-red-700/10 px-0.5 text-[color-mix(in_srgb,var(--athar-ink)_38%,#d65342)] underline decoration-red-700/50 decoration-2 underline-offset-4" : undefined} key={`${match.verse_key}-${index}`}>
                              {word}{" "}
                            </span>
                          ))}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : mutashabihat ? <StatusState className="justify-center">لا توجد آيات متشابهة بدرجة معتبرة لهذه الآية.</StatusState> : null}
            </div>
          ) : null}

          {activeTool === "asbab" ? (
            <div className="mt-4 grid gap-3">
              {!asbab && !asbabError ? <StatusState tone="loading">جارٍ مراجعة المصادر المحلية…</StatusState> : null}
              {asbabError ? <StatusState tone="error">{asbabError}</StatusState> : null}
              {asbab?.entries.length ? asbab.entries.map((entry, index) => (
                <article className="rounded-[13px] border border-athar-line-soft bg-athar-canvas p-4" key={`${entry.source}-${index}`}>
                  <p className="mb-2.5 mt-0 text-xs font-bold text-athar-gold">{entry.attribution || entry.source}</p>
                  <p className="m-0 whitespace-pre-line leading-8 text-athar-ink-soft">{entry.text.replace(/<br\s*\/?\s*>/gi, "\n")}</p>
                </article>
              )) : asbab ? (
                <StatusState className="justify-center">{asbab.message || "لم يثبت سبب نزول لهذه الآية في المصادر المحمّلة."}</StatusState>
              ) : null}
            </div>
          ) : null}

          {activeTool === "study" ? (
            <div className="mt-4 grid gap-2.5 sm:grid-cols-3">
              <a className="grid min-h-24 content-center gap-1 rounded-[13px] border border-athar-line p-4 no-underline transition hover:-translate-y-0.5 hover:border-athar-accent sm:min-h-[122px]" href={`/memorize?surah=${surahNumber}&from=${ayahNumber}&to=${ayahNumber}`}>
                <strong className="font-athar-display text-2xl text-athar-accent">تثبيت</strong><span className="text-xs text-athar-ink-soft">حفظ الآية بالتكرار والسياق الموضوعي</span>
              </a>
              <a className="grid min-h-24 content-center gap-1 rounded-[13px] border border-athar-line p-4 no-underline transition hover:-translate-y-0.5 hover:border-athar-accent sm:min-h-[122px]" href={`/waqf?surah=${surahNumber}&ayah=${ayahNumber}`}>
                <strong className="font-athar-display text-2xl text-athar-accent">مُكْث</strong><span className="text-xs text-athar-ink-soft">دراسة مواضع الوقف واختلاف القرّاء</span>
              </a>
              <a className="grid min-h-24 content-center gap-1 rounded-[13px] border border-athar-line p-4 no-underline transition hover:-translate-y-0.5 hover:border-athar-accent sm:min-h-[122px]" href={legacyUrl(`/waqf-practice?surah=${surahNumber}&ayah=${ayahNumber}`)}>
                <strong className="font-athar-display text-2xl text-athar-accent">تدريب</strong><span className="text-xs text-athar-ink-soft">اختبر قرارات الوقف داخل الآية</span>
              </a>
            </div>
          ) : null}
        </DrawerSurface>
      ) : null}
    </section>
  );
}
