"use client";

import {useEffect, useMemo, useState} from "react";
import {useSearchParams} from "next/navigation";
import {getJson, type Surah} from "@/lib/api";
import {arabicCount, toArabicDigits} from "@/lib/mushaf";
import {legacyUrl} from "@/lib/paths";
import {cn} from "@/lib/cn";
import {introLinkClassName} from "@/lib/ui";
import {ToolCard, ToolIntro, ToolStack} from "@/components/tool-chrome";
import {DoorIcon} from "@/components/ui/door-icon";
import {Button, SegmentedControl, StatusState} from "@/components/ui/primitives";
import {HitChip, HitList, HitRow, ToneChip, ToolBlurb} from "@/components/waqf-lab-hit";
import {LabClusterPanel, LabSolosPanel, LabStatsPanel} from "@/components/waqf-lab-reciters";
import {LabAgreementPanel, LabMandatoryPanel, LabMushafSimPanel, LabPatternsPanel} from "@/components/waqf-lab-mushafs";
import {
  HIT_PAGE,
  LAB_FAMILIES,
  LAB_TABS,
  WORD_PRESETS,
  familyForTab,
  isLabTab,
  labTool,
  type IbtidaaItem,
  type LabTab,
  type Saktah,
  type WordResearchPayload,
} from "@/lib/waqf-lab";

type WordMode = "before" | "";

/** The big search: a word, whether it must match exactly, and whether to read the mark on it or just before it. */
function WordSearchForm({
  query,
  exact,
  mode,
  large = false,
  onQueryChange,
  onExactChange,
  onModeChange,
  onSubmit,
}: {
  query: string;
  exact: boolean;
  mode: WordMode;
  large?: boolean;
  onQueryChange: (value: string) => void;
  onExactChange: (value: boolean) => void;
  onModeChange: (value: WordMode) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="grid gap-2.5"
      role="search"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <div className={cn(
        "flex items-center gap-2 rounded-2xl border border-athar-line bg-athar-surface p-1.5 shadow-athar-sm transition-colors focus-within:border-athar-accent",
        large && "p-2",
      )}>
        <DoorIcon name="search" className="ms-2 size-5 shrink-0 text-athar-ink-faint" />
        <input
          type="search"
          aria-label="ابحث عن أي كلمة"
          placeholder="اكتب كلمة من القرآن… مثل: كلا، ذلك، بلى"
          className={cn("min-h-11 min-w-0 flex-1 bg-transparent text-athar-ink outline-none placeholder:text-athar-ink-faint", large ? "text-lg" : "text-base")}
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
        <Button type="submit" variant="primary" className={cn("shrink-0 rounded-xl", large && "min-h-12 px-6")}>ابحث</Button>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl
          variant="pills"
          label="موضع العلامة"
          value={mode || "on"}
          options={[
            {value: "on", label: "العلامة على الكلمة"},
            {value: "before", label: "العلامة قبلها"},
          ]}
          onChange={(value) => onModeChange(value === "before" ? "before" : "")}
        />
        <label className="inline-flex min-h-9 cursor-pointer items-center gap-2 rounded-full border border-athar-line bg-athar-surface px-3 text-[0.8rem] font-semibold text-athar-ink-soft has-[:checked]:border-athar-accent has-[:checked]:text-athar-accent">
          <input type="checkbox" className="accent-athar-accent" checked={exact} onChange={(event) => onExactChange(event.target.checked)} />
          الكلمة نفسها فقط
        </label>
      </div>
    </form>
  );
}

function ExampleSearches({onPick, current}: {onPick: (word: string, exact: boolean, mode: WordMode) => void; current?: {query: string; mode: WordMode}}) {
  return (
    <div className="grid gap-3" aria-label="أمثلة للبحث">
      {WORD_PRESETS.map((group) => (
        <div className="flex flex-wrap items-center gap-1.5" key={group.group}>
          <span className="me-1 text-[0.74rem] font-bold text-athar-gold">{group.group}</span>
          {group.items.map((item) => {
            const active = current?.query === item.word && current.mode === (item.mode || "");
            return (
              <button
                type="button"
                key={`${item.word}-${item.mode || ""}`}
                className={cn(
                  "min-h-8 rounded-full border px-3 font-athar-quran text-[1.02rem] transition-colors",
                  active ? "border-athar-accent bg-athar-accent text-athar-on-accent" : "border-athar-line bg-athar-surface text-athar-ink hover:border-athar-accent hover:text-athar-accent",
                )}
                onClick={() => onPick(item.word, Boolean(item.exact), item.mode || "")}
              >
                {item.mode === "before" ? `… ${item.word}` : item.word}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}

/** All tools grouped by family, each introduced by the question it answers. */
function ToolGrid({onOpen}: {onOpen: (tab: LabTab) => void}) {
  return (
    <div className="grid gap-6">
      {LAB_FAMILIES.map((family) => (
        <section key={family.id} aria-labelledby={`lab-family-${family.id}`} className="grid gap-3">
          <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 id={`lab-family-${family.id}`} className="m-0 font-athar-display text-[1.25rem] text-athar-ink">{family.title}</h2>
            <p className="m-0 text-[0.84rem] text-athar-ink-soft">{family.description}</p>
          </header>
          <div className="grid grid-cols-3 gap-2.5 max-lg:grid-cols-2 max-sm:grid-cols-1">
            {LAB_TABS.filter((tool) => tool.family === family.id).map((tool) => (
              <button
                type="button"
                key={tool.id}
                onClick={() => onOpen(tool.id)}
                className="group grid gap-1.5 rounded-athar-md border border-athar-line bg-athar-surface p-4 text-start transition-[border-color,transform,box-shadow] hover:-translate-y-0.5 hover:border-athar-accent/50 hover:shadow-athar-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-athar-accent"
              >
                <span className="flex items-center justify-between gap-2">
                  <strong className="text-[1rem] text-athar-ink">{tool.label}</strong>
                  <span aria-hidden="true" className="text-athar-accent transition-transform group-hover:-translate-x-1">←</span>
                </span>
                <span className="text-[0.84rem] leading-6 text-athar-ink-soft">{tool.question}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

/** Desktop: a sticky list of every tool. Phones: one scrollable row. */
function ToolNav({tab, onOpen, onHome}: {tab: LabTab; onOpen: (tab: LabTab) => void; onHome: () => void}) {
  return (
    <>
      <nav className="sticky top-[calc(var(--bar-height)+1rem)] hidden max-h-[calc(100dvh-var(--bar-height)-2rem)] overflow-y-auto lg:block" aria-label="أدوات المختبر">
        <button type="button" onClick={onHome} className="mb-3 inline-flex items-center gap-1.5 text-[0.82rem] font-bold text-athar-accent hover:underline">
          <span aria-hidden="true">→</span> كل الأدوات
        </button>
        <div className="grid gap-4">
          {LAB_FAMILIES.map((family) => (
            <div key={family.id} className="grid gap-0.5">
              <span className="px-2.5 pb-1 text-[0.7rem] font-bold text-athar-gold">{family.title}</span>
              {LAB_TABS.filter((tool) => tool.family === family.id).map((tool) => (
                <button
                  type="button"
                  key={tool.id}
                  aria-current={tab === tool.id ? "page" : undefined}
                  title={tool.question}
                  onClick={() => onOpen(tool.id)}
                  className={cn(
                    "rounded-lg px-2.5 py-2 text-start text-[0.86rem] font-semibold transition-colors",
                    tab === tool.id ? "bg-athar-accent/10 text-athar-accent" : "text-athar-ink-soft hover:bg-athar-line-soft hover:text-athar-ink",
                  )}
                >
                  {tool.label}
                </button>
              ))}
            </div>
          ))}
        </div>
      </nav>
      <nav className="-mx-3 flex gap-1.5 overflow-x-auto px-3 pb-1 [scrollbar-width:none] lg:hidden" aria-label="أدوات المختبر">
        <button type="button" onClick={onHome} className="min-h-9 shrink-0 rounded-full border border-athar-line bg-athar-surface px-3 text-[0.8rem] font-bold text-athar-accent">
          كل الأدوات
        </button>
        {LAB_TABS.map((tool) => (
          <button
            type="button"
            key={tool.id}
            aria-current={tab === tool.id ? "page" : undefined}
            onClick={() => onOpen(tool.id)}
            className={cn(
              "min-h-9 shrink-0 rounded-full border px-3 text-[0.8rem] font-semibold whitespace-nowrap",
              tab === tool.id ? "border-athar-accent bg-athar-accent text-athar-on-accent" : "border-athar-line bg-athar-surface text-athar-ink-soft",
            )}
          >
            {tool.label}
          </button>
        ))}
      </nav>
    </>
  );
}

export function WaqfLabWorkspace() {
  const searchParams = useSearchParams();
  const bootQuery = searchParams.get("q")?.trim() || "";
  const bootTab = searchParams.get("tab");
  // No tool in the URL (and no query) opens the lab home.
  const [tab, setTab] = useState<LabTab | null>(isLabTab(bootTab) ? bootTab as LabTab : bootQuery ? "word" : null);
  const [surahs, setSurahs] = useState<Surah[]>([]);
  const [query, setQuery] = useState(bootQuery);
  const [exact, setExact] = useState(searchParams.get("exact") === "1");
  const [mode, setMode] = useState<WordMode>(searchParams.get("mode") === "before" ? "before" : "");
  const [searched, setSearched] = useState({query: bootQuery, mode: searchParams.get("mode") === "before" ? "before" as WordMode : ""});
  const [wordResult, setWordResult] = useState<WordResearchPayload | null>(null);
  const [wordForm, setWordForm] = useState<string | null>(null);
  const [wordWaqf, setWordWaqf] = useState<"" | "yes" | "no">("");
  const [wordLoading, setWordLoading] = useState(Boolean(bootQuery));
  const [wordError, setWordError] = useState("");
  const [wordShown, setWordShown] = useState(HIT_PAGE);
  const [ibtidaa, setIbtidaa] = useState<{count: number; multi_reciter: number; items: IbtidaaItem[]} | null>(null);
  const [ibtidaaMulti, setIbtidaaMulti] = useState(true);
  const [ibtidaaError, setIbtidaaError] = useState("");
  const [ibtidaaShown, setIbtidaaShown] = useState(HIT_PAGE);
  const [saktat, setSaktat] = useState<{obligatory: number; saktat: Saktah[]} | null>(null);
  const [saktatError, setSaktatError] = useState("");
  const tool = tab ? labTool(tab) : null;

  useEffect(() => {
    const controller = new AbortController();
    getJson<Surah[]>("/backend-api/surahs", controller.signal).then(setSurahs).catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (tab) {
      url.searchParams.set("tab", tab);
      url.searchParams.set("family", familyForTab(tab));
    } else {
      url.searchParams.delete("tab");
      url.searchParams.delete("family");
    }
    const wordParams = tab === "word" && searched.query;
    if (wordParams) url.searchParams.set("q", searched.query);
    else url.searchParams.delete("q");
    if (wordParams && exact) url.searchParams.set("exact", "1");
    else url.searchParams.delete("exact");
    if (wordParams && searched.mode) url.searchParams.set("mode", searched.mode);
    else url.searchParams.delete("mode");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }, [tab, searched, exact]);

  const openTool = (next: LabTab | null) => {
    setTab(next);
    window.scrollTo({top: 0, behavior: "smooth"});
  };

  const runWordSearch = (word: string, nextExact = exact, nextMode: WordMode = mode) => {
    const trimmed = word.trim();
    if (!trimmed) return;
    setTab("word");
    setQuery(trimmed);
    setExact(nextExact);
    setMode(nextMode);
    setSearched({query: trimmed, mode: nextMode});
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
      .catch(() => setWordError("تعذّر البحث — تحقّق من الاتصال ثم أعد المحاولة."))
      .finally(() => setWordLoading(false));
  };

  useEffect(() => {
    if (!bootQuery) return;
    const controller = new AbortController();
    const params = new URLSearchParams({word: bootQuery});
    if (searchParams.get("exact") === "1") params.set("exact", "1");
    if (searchParams.get("mode") === "before") params.set("mode", "before");
    getJson<WordResearchPayload>(`/backend-api/waqf-research?${params}`, controller.signal)
      .then((payload) => {
        setWordResult(payload);
        setWordForm(payload.active_form);
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setWordError("تعذّر البحث — تحقّق من الاتصال ثم أعد المحاولة.");
      })
      .finally(() => setWordLoading(false));
    return () => controller.abort();
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

  const wordSource = useMemo(() => (
    wordForm && wordResult ? wordResult.occurrences.filter((item) => item.form === wordForm) : wordResult?.occurrences || []
  ), [wordForm, wordResult]);
  const wordList = useMemo(() => {
    if (wordWaqf === "yes") return wordSource.filter((item) => item.has_waqf);
    if (wordWaqf === "no") return wordSource.filter((item) => !item.has_waqf);
    return wordSource;
  }, [wordSource, wordWaqf]);
  const wordWithMark = wordSource.filter((item) => item.has_waqf).length;
  const wordWithout = wordSource.length - wordWithMark;

  const ibtidaaItems = useMemo(() => {
    const all = ibtidaa?.items || [];
    return (ibtidaaMulti ? all.filter((item) => item.count >= 2) : all).slice(0, 300);
  }, [ibtidaa, ibtidaaMulti]);

  const searchForm = (large: boolean) => (
    <WordSearchForm
      large={large}
      query={query}
      exact={exact}
      mode={mode}
      onQueryChange={setQuery}
      onExactChange={setExact}
      onModeChange={setMode}
      onSubmit={() => runWordSearch(query, exact, mode)}
    />
  );

  return (
    <div aria-label="مساحة مختبر الوقف">
      <ToolIntro
        kicker="مختبر الوقف"
        tool="lab"
        title="ادرس الوقف عبر القرآن، لا آيةً واحدة."
        titleId="wq-lab-title"
        lede="ابحث عن كلمة، أو اختر سؤالًا من الأدوات أدناه. كل نتيجة تفتح موضعها في مُكْث بأدلته."
      >
        {process.env.NODE_ENV === "development" ? (
          <a className={introLinkClassName()} href={legacyUrl("/mushaf-editor")}>محرّر الوقف</a>
        ) : null}
      </ToolIntro>

      {!tab ? (
        <ToolStack className="gap-8">
          <section className="grid gap-4 rounded-athar-lg border border-athar-line bg-athar-surface/70 p-[clamp(16px,3vw,28px)]" aria-label="البحث بالكلمة">
            <div className="grid gap-1">
              <h2 className="m-0 font-athar-display text-[1.35rem] text-athar-ink">أين يُوقف على كلمةٍ ما؟</h2>
              <p className="m-0 text-[0.88rem] text-athar-ink-soft">اكتب أي كلمة لترى كل مواضعها في القرآن، وعلامة الوقف عليها في كل مصحف.</p>
            </div>
            {searchForm(true)}
            <ExampleSearches onPick={runWordSearch} />
          </section>
          <ToolGrid onOpen={openTool} />
        </ToolStack>
      ) : (
        <ToolStack className="lg:grid lg:grid-cols-[220px_minmax(0,1fr)] lg:items-start lg:gap-6">
          <ToolNav tab={tab} onOpen={openTool} onHome={() => openTool(null)} />
          <ToolCard raised aria-labelledby="wq-lab-panel-title" className="min-w-0">
            <header className="mb-4 grid gap-1 border-b border-athar-line-soft pb-3">
              <span className="text-[0.72rem] font-bold text-athar-gold">{LAB_FAMILIES.find((family) => family.id === tool!.family)?.title}</span>
              <h2 className="m-0 font-athar-display text-[1.3rem] text-athar-ink" id="wq-lab-panel-title">{tool!.label}</h2>
              <p className="m-0 text-[0.88rem] text-athar-ink-soft">{tool!.question}</p>
            </header>

            {tab === "word" ? (
              <div className="grid gap-4">
                {searchForm(false)}
                {wordLoading ? <StatusState tone="loading">جارٍ البحث في القرآن…</StatusState> : null}
                {wordError ? <StatusState tone="error">{wordError}</StatusState> : null}
                {!wordResult && !wordLoading ? <ExampleSearches onPick={runWordSearch} /> : null}
                {wordResult && !wordLoading ? (
                  wordResult.occurrences.length ? (
                    <div className="grid gap-3">
                      <div className="grid gap-2 rounded-xl border border-athar-line-soft bg-athar-canvas/70 p-3" aria-label="ملخص النتائج">
                        <p className="m-0 text-[0.95rem] text-athar-ink">
                          «<span className="font-athar-quran text-[1.08em]">{searched.query}</span>»:{" "}
                          <b>{arabicCount(wordSource.length, ["موضع واحد", "موضعان", "مواضع", "موضعًا"])}</b>
                          {searched.mode === "before" ? " — العلامة على الكلمة قبلها" : ""}
                          {wordSource.length ? <> · <b className="text-athar-accent">{toArabicDigits(wordWithMark)}</b> منها بعلامة وقف</> : null}
                        </p>
                        {wordSource.length ? (
                          <span className="block h-1.5 overflow-hidden rounded-full bg-athar-line-soft" aria-hidden="true">
                            <span className="block h-full rounded-full bg-athar-accent" style={{width: `${(wordWithMark / wordSource.length) * 100}%`}} />
                          </span>
                        ) : null}
                      </div>
                      {wordResult.forms.length > 1 ? (
                        <div className="flex flex-wrap items-center gap-1.5" aria-label="الصيغة">
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
                  ) : (
                    <StatusState>
                      لا توجد مواضع لـ«{searched.query}».{exact ? " جرّب إلغاء «الكلمة نفسها فقط» ليشمل البحث صيغها الأخرى." : " تأكّد من الإملاء، أو جرّب كلمة من الأمثلة."}
                    </StatusState>
                  )
                ) : null}
              </div>
            ) : null}

            {tab === "ibtidaa" ? (
              ibtidaaError ? <StatusState tone="error">{ibtidaaError}</StatusState>
              : !ibtidaa ? <StatusState tone="loading">جارٍ تحليل تلاوات القرّاء…</StatusState>
              : (
                <div className="grid gap-3">
                  <ToolBlurb
                    shortText="كلّما زاد عدد القرّاء الذين رجعوا في الموضع نفسه قوي الدليل على أن ما بعده لا يُبتدأ به."
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
      )}
    </div>
  );
}
