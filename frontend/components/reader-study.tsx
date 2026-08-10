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
    <section className="reader-study" aria-label="أدوات فهم الآية">
      <div className="reader-tool-row">
        {tools.map((tool) => (
          <button
            key={tool.id}
            type="button"
            aria-expanded={activeTool === tool.id}
            aria-controls="reader-study-drawer"
            onClick={() => setActiveTool((current) => current === tool.id ? null : tool.id)}
          >
            {tool.label}
          </button>
        ))}
      </div>

      {activeTool ? (
        <div className="reader-study-drawer" id="reader-study-drawer">
          <header>
            <div>
              <span className="reader-panel-kicker">الآية {surahNumber}:{ayahNumber}</span>
              <h2>{activeLabel}</h2>
            </div>
            <button type="button" className="reader-panel-close" onClick={() => setActiveTool(null)} aria-label="إغلاق أداة الدراسة">×</button>
          </header>

          {needsAyah && !ayahData && !verseError ? <div className="reader-panel-loading">جارٍ تحميل بيانات الآية…</div> : null}
          {verseError ? <div className="reader-panel-error" role="alert">{verseError}</div> : null}

          {activeTool === "meanings" && ayahData ? (
            <div className="reader-meanings">
              {ayahData.word_meanings_source?.attribution ? (
                <p className="reader-panel-credit">المصدر: {ayahData.word_meanings_source.attribution}</p>
              ) : null}
              {ayahData.word_meanings_ordered?.length ? (
                <dl>
                  {ayahData.word_meanings_ordered.map((entry, index) => (
                    <div key={`${entry.word_no}-${entry.word}-${index}`}>
                      <dt>{entry.word}</dt>
                      <dd>{entry.meaning}</dd>
                    </div>
                  ))}
                </dl>
              ) : <p className="reader-empty">لا توجد معاني كلمات متاحة لهذه الآية.</p>}
            </div>
          ) : null}

          {activeTool === "transliteration" && ayahData ? (
            ayahData.transliteration?.t
              ? <p className="reader-transliteration" dir="ltr">{ayahData.transliteration.t}</p>
              : <p className="reader-empty">لا يتوفر نقل حرفي لهذه الآية.</p>
          ) : null}

          {activeTool === "tafseer" ? (
            <div className="reader-tafseer">
              {!tafseers && !tafseerError ? <div className="reader-panel-loading">جارٍ تحميل التفاسير المحلية…</div> : null}
              {tafseerError ? <div className="reader-panel-error" role="alert">{tafseerError}</div> : null}
              {tafseers && Object.keys(tafseers).length ? (
                <>
                  <label><span>المصدر</span>
                    <select value={selectedTafseer} onChange={(event) => {
                      setSelectedTafseer(event.target.value);
                      window.localStorage.setItem("athar-reader-tafseer", event.target.value);
                    }}>
                      {Object.keys(tafseers).map((name) => <option key={name} value={name}>{name}</option>)}
                    </select>
                  </label>
                  <p>{tafseerText}</p>
                </>
              ) : tafseers ? <p className="reader-empty">لا يتوفر تفسير محلي لهذه الآية.</p> : null}
            </div>
          ) : null}

          {activeTool === "mutashabihat" ? (
            <div className="reader-mutashabihat">
              {!mutashabihat && !mutashabihatError ? <div className="reader-panel-loading">جارٍ البحث في المواضع المتشابهة…</div> : null}
              {mutashabihatError ? <div className="reader-panel-error" role="alert">{mutashabihatError}</div> : null}
              {mutashabihat?.matches.length ? (
                <div className="reader-mutashabihat-list">
                  {mutashabihat.matches.map((match) => {
                    const differing = differingWordIndexes(match);
                    const surahName = surahs.find((surah) => surah.number === match.surah)?.name || `سورة ${toArabicDigits(match.surah)}`;
                    return (
                      <button
                        type="button"
                        className="reader-mutashabih-item"
                        key={match.verse_key}
                        onClick={() => onNavigate(match.surah, match.ayah)}
                        aria-label={`انتقل إلى سورة ${surahName} الآية ${toArabicDigits(match.ayah)}`}
                      >
                        <span className="reader-mutashabih-head">
                          <strong>{surahName} · {toArabicDigits(match.ayah)}</strong>
                          <small>{match.near_duplicate ? "شبه مطابقة" : runLabel(match.longest_run)}</small>
                        </span>
                        <span className="reader-mutashabih-verse" dir="rtl">
                          {match.words.map((word, index) => (
                            <span className={differing.has(index) ? "is-different" : undefined} key={`${match.verse_key}-${index}`}>
                              {word}{" "}
                            </span>
                          ))}
                        </span>
                      </button>
                    );
                  })}
                </div>
              ) : mutashabihat ? <p className="reader-empty">لا توجد آيات متشابهة بدرجة معتبرة لهذه الآية.</p> : null}
            </div>
          ) : null}

          {activeTool === "asbab" ? (
            <div className="reader-asbab">
              {!asbab && !asbabError ? <div className="reader-panel-loading">جارٍ مراجعة المصادر المحلية…</div> : null}
              {asbabError ? <div className="reader-panel-error" role="alert">{asbabError}</div> : null}
              {asbab?.entries.length ? asbab.entries.map((entry, index) => (
                <article key={`${entry.source}-${index}`}>
                  <p className="reader-asbab-attribution">{entry.attribution || entry.source}</p>
                  <p>{entry.text.replace(/<br\s*\/?\s*>/gi, "\n")}</p>
                </article>
              )) : asbab ? (
                <p className="reader-empty">{asbab.message || "لم يثبت سبب نزول لهذه الآية في المصادر المحمّلة."}</p>
              ) : null}
            </div>
          ) : null}

          {activeTool === "study" ? (
            <div className="reader-study-links">
              <a href={legacyUrl(`/memorize?surah=${surahNumber}&ayah=${ayahNumber}`)}>
                <strong>تثبيت</strong><span>حفظ الآية بالتكرار والسياق الموضوعي</span>
              </a>
              <a href={legacyUrl(`/waqf?surah=${surahNumber}&ayah=${ayahNumber}`)}>
                <strong>مُكْث</strong><span>دراسة مواضع الوقف واختلاف القرّاء</span>
              </a>
              <a href={legacyUrl(`/waqf-practice?surah=${surahNumber}&ayah=${ayahNumber}`)}>
                <strong>تدريب</strong><span>اختبر قرارات الوقف داخل الآية</span>
              </a>
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
