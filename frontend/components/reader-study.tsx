"use client";

import { useEffect, useMemo, useState } from "react";
import { getJson, type Ayah, type TafseerCollection } from "@/lib/api";
import { legacyUrl } from "@/lib/paths";

type StudyTool = "meanings" | "tafseer" | "transliteration" | "study";

type ReaderStudyProps = {
  surahNumber: number;
  ayahNumber: number;
  initialAyah: Ayah | null;
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

const verseCache = new Map<string, Ayah>();
const tafseerCache = new Map<string, Record<string, string>>();

const tools: Array<{id: StudyTool; label: string}> = [
  {id: "meanings", label: "معاني الكلمات"},
  {id: "tafseer", label: "التفسير"},
  {id: "transliteration", label: "النطق الحرفي"},
  {id: "study", label: "أدوات الدراسة"},
];

function plainTextFromHtml(html: string) {
  const template = document.createElement("template");
  template.innerHTML = html;
  template.content.querySelectorAll("script, style").forEach((element) => element.remove());
  return (template.content.textContent || "").replace(/\s+/g, " ").trim();
}

export function ReaderStudy({surahNumber, ayahNumber, initialAyah}: ReaderStudyProps) {
  const [activeTool, setActiveTool] = useState<StudyTool | null>(null);
  const [verseResult, setVerseResult] = useState<VerseResult>({key: "", data: null, error: ""});
  const [tafseerResult, setTafseerResult] = useState<TafseerResult>({key: "", data: null, error: ""});
  const [selectedTafseer, setSelectedTafseer] = useState("");
  const verseKey = `${surahNumber}:${ayahNumber}`;
  const ayahData = initialAyah?.verse_key === verseKey
    ? initialAyah
    : verseResult.key === verseKey ? verseResult.data : null;
  const verseError = verseResult.key === verseKey ? verseResult.error : "";
  const tafseers = tafseerResult.key === verseKey ? tafseerResult.data : null;
  const tafseerError = tafseerResult.key === verseKey ? tafseerResult.error : "";
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
