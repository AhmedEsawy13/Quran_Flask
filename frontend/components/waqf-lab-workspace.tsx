"use client";

import {useEffect, useMemo, useState} from "react";
import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {getJson, type Surah} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {legacyUrl} from "@/lib/paths";
import {cn} from "@/lib/cn";
import {introLinkClassName} from "@/lib/ui";
import {
  ChromeField,
  ChromeInput,
  ChromePill,
  ToolCard,
  ToolCardHead,
  ToolChrome,
  ToolIntro,
  ToolStack,
} from "@/components/tool-chrome";
import {Button, CheckControl, DrawerSurface, SegmentedControl, StatusState} from "@/components/ui/primitives";
import {CountLabel, HitChip, HitList, HitRow, ToneChip, ToolBlurb} from "@/components/waqf-lab-hit";
import {LabClusterPanel, LabSolosPanel, LabStatsPanel} from "@/components/waqf-lab-reciters";
import {LabAgreementPanel, LabMandatoryPanel, LabMushafSimPanel, LabPatternsPanel} from "@/components/waqf-lab-mushafs";
import {
  HIT_PAGE,
  LAB_FAMILIES,
  LAB_TABS,
  WORD_PRESETS,
  familyForTab,
  firstTabForFamily,
  isLabFamily,
  isLabTab,
  type IbtidaaItem,
  type LabFamily,
  type LabTab,
  type Saktah,
  type WordResearchPayload,
} from "@/lib/waqf-lab";

export function WaqfLabWorkspace() {
  const searchParams = useSearchParams();
  const initialTab = isLabTab(searchParams.get("tab")) ? searchParams.get("tab") as LabTab : "word";
  const initialFamily = isLabFamily(searchParams.get("family")) ? searchParams.get("family") as LabFamily : familyForTab(initialTab);
  const [family, setFamily] = useState<LabFamily>(initialFamily);
  const [tab, setTab] = useState<LabTab>(familyForTab(initialTab) === initialFamily ? initialTab : firstTabForFamily(initialFamily));
  const [pickerOpen, setPickerOpen] = useState(false);
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [query, setQuery] = useState(searchParams.get("q") || "");
  const [exact, setExact] = useState(searchParams.get("exact") === "1");
  const [mode, setMode] = useState<"before" | "">(searchParams.get("mode") === "before" ? "before" : "");
  const [wordResult, setWordResult] = useState<WordResearchPayload | null>(null);
  const [wordForm, setWordForm] = useState<string | null>(null);
  const [wordWaqf, setWordWaqf] = useState<"" | "yes" | "no">("");
  const [wordLoading, setWordLoading] = useState(false);
  const [wordError, setWordError] = useState("");
  const [wordShown, setWordShown] = useState(HIT_PAGE);
  const [ibtidaa, setIbtidaa] = useState<{count: number; multi_reciter: number; items: IbtidaaItem[]} | null>(null);
  const [ibtidaaMulti, setIbtidaaMulti] = useState(true);
  const [ibtidaaError, setIbtidaaError] = useState("");
  const [ibtidaaShown, setIbtidaaShown] = useState(HIT_PAGE);
  const [saktat, setSaktat] = useState<{obligatory: number; saktat: Saktah[]} | null>(null);
  const [saktatError, setSaktatError] = useState("");

  const familyTabs = useMemo(() => LAB_TABS.filter((item) => item.family === family), [family]);
  const activeLabel = LAB_TABS.find((item) => item.id === tab)?.label || "بحث بالكلمة";
  const familyTitle = LAB_FAMILIES.find((item) => item.id === family)?.title || "كلمات وأنماط";

  useEffect(() => {
    const controller = new AbortController();
    getJson<Surah[]>("/backend-api/surahs", controller.signal).then(setSurahs).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", tab);
    url.searchParams.set("family", family);
    if (tab === "word" && query.trim()) url.searchParams.set("q", query.trim());
    else url.searchParams.delete("q");
    if (tab === "word" && exact) url.searchParams.set("exact", "1");
    else url.searchParams.delete("exact");
    if (tab === "word" && mode) url.searchParams.set("mode", mode);
    else url.searchParams.delete("mode");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [tab, family, query, exact, mode]);

  const selectFamily = (next: LabFamily) => {
    setFamily(next);
    setTab(firstTabForFamily(next));
    setPickerOpen(false);
  };

  const selectTab = (next: LabTab) => {
    setFamily(familyForTab(next));
    setTab(next);
    setPickerOpen(false);
  };

  const runWordSearch = (word: string, nextExact = exact, nextMode: "before" | "" = mode) => {
    const trimmed = word.trim();
    if (!trimmed) return;
    setQuery(trimmed);
    setExact(nextExact);
    setMode(nextMode);
    setWordForm(null);
    setWordWaqf("");
    setWordShown(HIT_PAGE);
    setWordLoading(true);
    setWordError("");
    const params = new URLSearchParams({word: trimmed});
    if (nextExact) params.set("exact", "1");
    if (nextMode) params.set("mode", nextMode);
    getJson<WordResearchPayload>(`/backend-api/waqf-research?${params}`)
      .then((payload) => {
        setWordResult(payload);
        setWordForm(payload.active_form);
      })
      .catch(() => setWordError("تعذّر البحث"))
      .finally(() => setWordLoading(false));
  };

  useEffect(() => {
    const initial = searchParams.get("q")?.trim();
    if (initial) runWordSearch(initial, searchParams.get("exact") === "1", searchParams.get("mode") === "before" ? "before" : "");
    // Initial deep-link only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (tab !== "ibtidaa" || ibtidaa) return;
    getJson<{count: number; multi_reciter: number; items: IbtidaaItem[]}>("/backend-api/waqf-research/ibtidaa")
      .then(setIbtidaa)
      .catch(() => setIbtidaaError("تعذّر التحميل"));
  }, [tab, ibtidaa]);

  useEffect(() => {
    if (tab !== "saktat" || saktat) return;
    getJson<{obligatory: number; saktat: Saktah[]}>("/backend-api/waqf-research/saktat")
      .then(setSaktat)
      .catch(() => setSaktatError("تعذّر التحميل"));
  }, [tab, saktat]);

  const wordList = useMemo(() => {
    if (!wordResult) return [];
    const byForm = wordForm ? wordResult.occurrences.filter((item) => item.form === wordForm) : wordResult.occurrences;
    if (wordWaqf === "yes") return byForm.filter((item) => item.has_waqf);
    if (wordWaqf === "no") return byForm.filter((item) => !item.has_waqf);
    return byForm;
  }, [wordResult, wordForm, wordWaqf]);

  const ibtidaaItems = useMemo(() => {
    const all = ibtidaa?.items || [];
    return (ibtidaaMulti ? all.filter((item) => item.count >= 2) : all).slice(0, 300);
  }, [ibtidaa, ibtidaaMulti]);

  const wordSource = wordForm && wordResult
    ? wordResult.occurrences.filter((item) => item.form === wordForm)
    : wordResult?.occurrences || [];
  const wordWithMark = wordSource.filter((item) => item.has_waqf).length;
  const wordWithout = wordSource.length - wordWithMark;

  return (
    <div aria-label="مساحة مختبر الوقف">
      <ToolIntro
        kicker="— مختبر الوقف"
        title="ادرس عبر القرآن، لا آيةً واحدة فقط."
        titleId="wq-lab-title"
        lede="ثلاث عائلات بحث: كلمات وأنماط، قرّاء، ومصاحف. أي نتيجة تفتح موضعها في مُكْث."
      >
        <Link className={introLinkClassName()} href="/waqf">← العودة إلى مُكْث</Link>
        <a className={introLinkClassName()} href={legacyUrl("/mushaf-editor")}>محرّر الوقف</a>
      </ToolIntro>

      <ToolChrome
        label="عائلات مختبر الوقف"
        pill={<ChromePill>{familyTitle} · {activeLabel}</ChromePill>}
      >
        <div
          className="flex min-h-11 flex-wrap items-center rounded-xl border border-athar-line bg-athar-canvas-strong p-1"
          role="tablist"
          aria-label="عائلات مختبر الوقف"
        >
          {LAB_FAMILIES.map((item) => (
            <button
              type="button"
              role="tab"
              aria-selected={family === item.id}
              className={cn(
                "min-h-9 rounded-[9px] px-3 text-sm font-semibold transition-colors",
                family === item.id ? "bg-athar-surface text-athar-accent shadow-sm" : "text-athar-ink-soft hover:text-athar-ink",
              )}
              onClick={() => selectFamily(item.id)}
              key={item.id}
            >
              {item.title}
            </button>
          ))}
        </div>
        {tab === "word" ? (
          <form
            className="flex min-w-0 flex-1 flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              runWordSearch(query, exact, mode);
            }}
          >
            <ChromeField label="الكلمة" className="min-w-[12rem] flex-[1.4]">
              <ChromeInput
                type="search"
                aria-label="ابحث عن أي كلمة"
                placeholder="ابحث عن أي كلمة…"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </ChromeField>
            <CheckControl
              label="مطابقة تامة"
              checked={exact}
              onChange={(event) => setExact(event.target.checked)}
              className="self-end"
            />
            <Button type="submit" className="self-end">ابحث</Button>
          </form>
        ) : null}
        <div className="hidden min-w-0 flex-1 flex-wrap gap-1.5 md:flex" role="tablist" aria-label="أقسام مختبر الوقف">
          {familyTabs.map((item) => (
            <Button
              key={item.id}
              size="sm"
              variant={tab === item.id ? "primary" : "secondary"}
              aria-selected={tab === item.id}
              onClick={() => selectTab(item.id)}
            >
              {item.label}
            </Button>
          ))}
        </div>
        <Button
          size="sm"
          variant="secondary"
          className="self-end md:hidden"
          aria-expanded={pickerOpen}
          aria-haspopup="dialog"
          aria-controls="waqf-lab-picker"
          onClick={() => setPickerOpen(true)}
        >
          {activeLabel}
        </Button>
      </ToolChrome>

      <DrawerSurface
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        title="أقسام المختبر"
        id="waqf-lab-picker"
        overlay
      >
        <div className="grid gap-1.5" role="listbox" aria-label="أقسام مختبر الوقف">
          {familyTabs.map((item) => (
            <button
              type="button"
              role="option"
              aria-selected={tab === item.id}
              className={cn(
                "min-h-12 rounded-xl border px-3 text-start text-sm font-bold",
                tab === item.id
                  ? "border-athar-accent bg-athar-accent/10 text-athar-accent"
                  : "border-athar-line-soft text-athar-ink",
              )}
              onClick={() => selectTab(item.id)}
              key={item.id}
            >
              {item.label}
            </button>
          ))}
        </div>
      </DrawerSurface>

      <ToolStack>
        <ToolCard raised aria-labelledby="wq-lab-panel-title">
          <ToolCardHead title={activeLabel} titleId="wq-lab-panel-title" />
          {tab === "word" ? (
            <div className="grid gap-3">
              <ToolBlurb shortText="ابحث عن كلمة أو نمطًا، ثم افتح الآية في مُكْث." />
              <details className="text-sm">
                <summary className="cursor-pointer font-semibold text-athar-ink-soft">أمثلة شائعة</summary>
                <div className="mt-2 grid gap-3">
                  {WORD_PRESETS.map((group) => (
                    <div className="grid gap-1.5" key={group.group}>
                      <span className="text-[0.72rem] font-bold text-athar-gold">{group.group}</span>
                      <div className="flex flex-wrap gap-1.5">
                        {group.items.map((item) => (
                          <Button
                            key={`${item.word}-${item.mode || ""}`}
                            size="sm"
                            variant={query === item.word && mode === (item.mode || "") ? "primary" : "secondary"}
                            onClick={() => runWordSearch(item.word, Boolean(item.exact), item.mode || "")}
                          >
                            {item.word}
                          </Button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
              {wordLoading ? <StatusState tone="loading">جارٍ البحث…</StatusState> : null}
              {wordError ? <StatusState tone="error">{wordError}</StatusState> : null}
              {wordResult && !wordLoading ? (
                <div className="grid gap-3">
                  {wordResult.forms.length > 1 ? (
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[0.72rem] font-bold text-athar-ink-faint">الصيغة</span>
                      <Button size="sm" variant={!wordForm ? "primary" : "secondary"} onClick={() => { setWordForm(null); setWordShown(HIT_PAGE); }}>
                        الكل <b>{toArabicDigits(wordResult.occurrences.length)}</b>
                      </Button>
                      {wordResult.forms.map((form) => (
                        <Button key={form.word} size="sm" variant={wordForm === form.word ? "primary" : "secondary"} onClick={() => { setWordForm(form.word); setWordShown(HIT_PAGE); }}>
                          <span className="font-athar-quran">{form.word}</span> <b>{toArabicDigits(form.count)}</b>
                        </Button>
                      ))}
                    </div>
                  ) : null}
                  {wordWithMark && wordWithout ? (
                    <SegmentedControl
                      variant="pills"
                      className="h-auto w-fit flex-wrap"
                      label="الوقف"
                      value={wordWaqf || "all"}
                      options={[
                        {value: "all", label: "الكل"},
                        {value: "yes", label: `بعلامة وقف ${toArabicDigits(wordWithMark)}`},
                        {value: "no", label: `بلا علامة ${toArabicDigits(wordWithout)}`},
                      ]}
                      onChange={(value) => {
                        setWordWaqf(value === "all" ? "" : value);
                        setWordShown(HIT_PAGE);
                      }}
                    />
                  ) : null}
                  {mode === "before" ? (
                    <p className="m-0 text-[0.82rem] text-athar-ink-soft">علامات الوقف على الكلمة <b>قبل</b> «{query}»</p>
                  ) : null}
                  <CountLabel>{toArabicDigits(wordList.length)} موضعًا</CountLabel>
                  <HitList
                    items={wordList}
                    shown={wordShown}
                    onShowMore={() => setWordShown((value) => value + HIT_PAGE)}
                    renderItem={(item, index) => (
                      <HitRow
                        occurrence={item}
                        surahName={surahs.find((surah) => surah.number === item.surah)?.name}
                        key={`${item.surah}:${item.ayah}:${item.wpos}:${index}`}
                      />
                    )}
                  />
                </div>
              ) : null}
            </div>
          ) : null}

          {tab === "ibtidaa" ? (
            ibtidaaError ? <StatusState tone="error">{ibtidaaError}</StatusState>
            : !ibtidaa ? <StatusState tone="loading">جارٍ تحليل تلاوات القرّاء…</StatusState>
            : (
              <div className="grid gap-3">
                <ToolBlurb
                  shortText="وقف ثم ابتداء بما قبله — من تلاوات القرّاء."
                  longText="مواضع وقف عليها القارئ ثم عاد فقرأ من كلمة قبلها. كلّما زاد عدد القرّاء الذين رجعوا في الموضع نفسه قوي الدليل."
                />
                <SegmentedControl
                  variant="pills"
                  className="h-auto w-fit flex-wrap"
                  label="تصفية الابتداء"
                  value={ibtidaaMulti ? "multi" : "all"}
                  options={[
                    {value: "multi", label: `قارئان فأكثر (${toArabicDigits(ibtidaa.multi_reciter)})`},
                    {value: "all", label: `الكل (${toArabicDigits(ibtidaa.count)})`},
                  ]}
                  onChange={(value) => {
                    setIbtidaaMulti(value === "multi");
                    setIbtidaaShown(HIT_PAGE);
                  }}
                />
                <HitList
                  items={ibtidaaItems}
                  shown={ibtidaaShown}
                  onShowMore={() => setIbtidaaShown((value) => value + HIT_PAGE)}
                  renderItem={(item, index) => (
                    <HitRow
                      occurrence={{surah: item.surah, ayah: item.ayah, word: item.stop_word, context: item.context}}
                      hideMarks
                      surahName={surahs.find((surah) => surah.number === item.surah)?.name}
                      title={(item.reciters || []).join("، ")}
                      meta={(
                        <>
                          <ToneChip tone="accent">{toArabicDigits(item.count)} قارئ</ToneChip>
                          <span className="text-[0.7rem] text-athar-ink-soft">{item.stop_marked ? "عليه علامة" : "بلا علامة"}</span>
                        </>
                      )}
                      flow={(
                        <>
                          يقف على <HitChip>{item.stop_word}</HitChip>
                          <HitChip muted>ثم يبدأ من</HitChip>
                          <HitChip>{item.resume_word}</HitChip>
                          <HitChip muted>
                            {item.back_distance === 0 ? "أعاد الكلمة نفسها" : `رجع ${toArabicDigits(item.back_distance)} ${item.back_distance <= 2 ? "كلمة" : "كلمات"}`}
                          </HitChip>
                        </>
                      )}
                      key={`${item.surah}:${item.ayah}:${index}`}
                    />
                  )}
                />
              </div>
            )
          ) : null}

          {tab === "saktat" ? (
            saktatError ? <StatusState tone="error">{saktatError}</StatusState>
            : !saktat ? <StatusState tone="loading">جارٍ التحميل…</StatusState>
            : (
              <div className="grid gap-3">
                <ToolBlurb shortText={`سكتات حفص: ${toArabicDigits(saktat.obligatory)} واجبة — وقفة يسيرة بلا تنفّس.`} />
                <HitList
                  items={saktat.saktat}
                  shown={saktat.saktat.length}
                  onShowMore={() => undefined}
                  renderItem={(item) => (
                    <HitRow
                      occurrence={{surah: item.surah, ayah: item.ayah, wpos: item.wpos, word: item.on_word, context: item.reason || item.context}}
                      hideMarks
                      surahName={item.name || surahs.find((surah) => surah.number === item.surah)?.name}
                      meta={(
                        <>
                          <ToneChip tone={item.category === "واجبة" ? "accent" : "muted"}>
                            {item.category === "واجبة" ? "واجبة" : "جائزة بوجهين"}
                          </ToneChip>
                          {item.cross_verse ? (
                            <span className="text-[0.7rem] text-athar-ink-faint">
                              بين {toArabicDigits(item.surah)}:{toArabicDigits(item.ayah)} و{toArabicDigits(item.next.surah)}:{toArabicDigits(item.next.ayah)}
                            </span>
                          ) : null}
                        </>
                      )}
                      flow={(
                        <>
                          سكتة على <HitChip>{item.on_word}</HitChip>
                          <HitChip muted>ثم</HitChip>
                          <HitChip>{item.next_word}</HitChip>
                        </>
                      )}
                      key={`${item.surah}:${item.ayah}:${item.wpos}`}
                    />
                  )}
                />
              </div>
            )
          ) : null}

          {tab === "mandatory" ? <LabMandatoryPanel surahs={surahs} /> : null}
          {tab === "solos" ? <LabSolosPanel surahs={surahs} /> : null}
          {tab === "stats" ? <LabStatsPanel surahs={surahs} /> : null}
          {tab === "cluster" ? <LabClusterPanel /> : null}
          {tab === "patterns" ? <LabPatternsPanel surahs={surahs} /> : null}
          {tab === "agreement" ? <LabAgreementPanel surahs={surahs} /> : null}
          {tab === "mushafsim" ? <LabMushafSimPanel surahs={surahs} /> : null}
        </ToolCard>
      </ToolStack>
    </div>
  );
}
