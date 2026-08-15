"use client";

import {useEffect, useMemo, useState} from "react";
import {getJson, type Surah} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {cn} from "@/lib/cn";
import {waqfMarkGlyph, waqfMarkLabel} from "@/lib/waqf";
import {ChromeField, ChromeSelect} from "@/components/tool-chrome";
import {Button, SegmentedControl, StatusState} from "@/components/ui/primitives";
import {AgreePill, CountLabel, HitChip, HitList, HitMarks, HitRow, LabNarrow, LabTable, LabWide, ToolBlurb} from "@/components/waqf-lab-hit";
import {
  HIT_PAGE,
  agreeDesc,
  agreeVerb,
  mushafFontClass,
  mushafGlyph,
  type AgreeCasesPayload,
  type AgreementPayload,
  type MandatoryPayload,
  type MushafDiffPayload,
  type MushafSimPayload,
  type MushafSimTree,
  type ResearchOccurrence,
} from "@/lib/waqf-lab";

const SYSTEM_LABEL: Record<string, string> = {
  standard: "نظام حفص القياسي",
  warsh: "رواية ورش",
  indopak: "النظام الباكستاني (IndoPak)",
};

function pct(cell?: [number, number]) {
  return cell && cell[1] ? Math.round((cell[0] / cell[1]) * 100) : null;
}

function placedTree(tree: MushafSimTree, order: string[]) {
  const rowH = 40;
  const padTop = 18;
  const padBot = 10;
  const width = 600;
  const labelW = 150;
  const xLeaf = width - labelW;
  const xRoot = 30;
  const yOf = Object.fromEntries(order.map((id, index) => [id, padTop + index * rowH + rowH / 2]));
  const sims: number[] = [];
  const collect = (node: MushafSimTree) => {
    if (node.type === "node") {
      sims.push(node.similarity);
      node.children.forEach(collect);
    }
  };
  collect(tree);
  const minSim = sims.length ? Math.min(1, ...sims) : 1;
  const sx = (similarity: number) => (minSim >= 1 ? xRoot : xLeaf - ((1 - similarity) / (1 - minSim)) * (xLeaf - xRoot));
  type Placed = MushafSimTree & {_x: number; _y: number};
  const segments: Array<[number, number, number, number]> = [];
  const forks: Placed[] = [];
  const leaves: Placed[] = [];
  const place = (node: MushafSimTree): Placed => {
    if (node.type === "leaf") {
      const placed = {...node, _x: xLeaf, _y: yOf[node.id] || padTop};
      leaves.push(placed);
      return placed;
    }
    const children = node.children.map(place);
    const ys = children.map((child) => child._y);
    const placed = {...node, _x: sx(node.similarity), _y: (Math.min(...ys) + Math.max(...ys)) / 2, children};
    segments.push([placed._x, Math.min(...ys), placed._x, Math.max(...ys)]);
    children.forEach((child) => segments.push([placed._x, child._y, child._x, child._y]));
    forks.push(placed);
    return placed;
  };
  place(tree);
  return {width, height: padTop + order.length * rowH + padBot, segments, forks, leaves, xLeaf};
}

export function LabPatternsPanel({surahs}: {surahs: Surah[]}) {
  const [items, setItems] = useState<ResearchOccurrence[] | null>(null);
  const [error, setError] = useState("");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    const controller = new AbortController();
    getJson<{disagreements: ResearchOccurrence[]}>("/backend-api/waqf-research/patterns", controller.signal)
      .then((payload) => setItems(payload.disagreements || []))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!items) return <StatusState tone="loading">جارٍ التحليل…</StatusState>;

  return (
    <div className="grid gap-3">
      <ToolBlurb shortText="مواضع اختلفت فيها المصاحف في علامة الوقف على نفس الكلمة." />
      <CountLabel>{toArabicDigits(items.length)} موضع اختلاف</CountLabel>
      <HitList
        items={items}
        shown={shown}
        onShowMore={() => setShown((value) => value + HIT_PAGE)}
        renderItem={(item, index) => (
          <HitRow
            occurrence={item}
            surahName={surahs.find((surah) => surah.number === item.surah)?.name}
            key={`${item.surah}:${item.ayah}:${index}`}
          />
        )}
      />
    </div>
  );
}

export function LabMandatoryPanel({surahs}: {surahs: Surah[]}) {
  const [data, setData] = useState<MandatoryPayload | null>(null);
  const [view, setView] = useState<"mandatory" | "forbidden" | "embracing">("mandatory");
  const [error, setError] = useState("");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    const controller = new AbortController();
    getJson<MandatoryPayload>("/backend-api/waqf-research/mandatory", controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!data) return <StatusState tone="loading">جارٍ التحميل…</StatusState>;

  const lists = {mandatory: data.mandatory || [], forbidden: data.forbidden || [], embracing: data.embracing || []};
  const items = lists[view];
  const descs = {
    mandatory: "مواضع الوقف اللازم (م) — يجب الوقف عليها",
    forbidden: "مواضع الوقف الممنوع (لا) — لا يصح الوقف عليها",
    embracing: "وقف المعانقة (ع) — يُوقف على أحد الموضعين فقط، لا كليهما",
  };

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap gap-1.5">
        {([["mandatory", "م", "اللازم"], ["forbidden", "لا", "الممنوع"], ["embracing", "ع", "المعانقة"]] as const).map(([value, mark, label]) => (
          <Button key={value} size="sm" variant={view === value ? "primary" : "secondary"} onClick={() => { setView(value); setShown(HIT_PAGE); }}>
            <span className="font-athar-quran">{waqfMarkGlyph(mark)}</span> {label} <b>{toArabicDigits(lists[value].length)}</b>
          </Button>
        ))}
      </div>
      <ToolBlurb shortText={descs[view]} />
      <HitList
        items={items}
        shown={shown}
        onShowMore={() => setShown((value) => value + HIT_PAGE)}
        renderItem={(item, index) => view === "embracing" ? (
          <HitRow
            occurrence={item}
            hideMarks
            surahName={surahs.find((surah) => surah.number === item.surah)?.name}
            meta={<AgreePill agreement={item.agreement} />}
            flow={(
              <div className="flex flex-wrap items-center gap-1.5">
                {(item.pair || []).map((part, partIndex) => (
                  <span className="contents" key={`${part.word}-${partIndex}`}>
                    {partIndex ? <HitChip muted>أو</HitChip> : null}
                    <HitChip>{part.word}</HitChip>
                    <HitMarks marks={part.marks} />
                  </span>
                ))}
              </div>
            )}
            key={`${item.surah}:${item.ayah}:${index}`}
          />
        ) : (
          <HitRow
            occurrence={item}
            surahName={surahs.find((surah) => surah.number === item.surah)?.name}
            meta={<AgreePill agreement={item.agreement} />}
            key={`${item.surah}:${item.ayah}:${item.wpos}:${index}`}
          />
        )}
      />
    </div>
  );
}

export function LabAgreementPanel({surahs}: {surahs: Surah[]}) {
  const [data, setData] = useState<AgreementPayload | null>(null);
  const [mushaf, setMushaf] = useState("");
  const [cases, setCases] = useState<{rid: string; mark: string; payload: AgreeCasesPayload} | null>(null);
  const [casesLoading, setCasesLoading] = useState(false);
  const [error, setError] = useState("");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    const controller = new AbortController();
    getJson<AgreementPayload>("/backend-api/waqf-research/mushaf-agreement", controller.signal)
      .then((payload) => {
        setData(payload);
        setMushaf((payload.mushafs || [])[0] || "");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  const marks = data && mushaf ? data.mark_config[mushaf] || [] : [];
  const jaizRange = useMemo(() => {
    if (!data || !mushaf) return {lo: 1, hi: 0};
    let lo = 1;
    let hi = 0;
    data.reciters.forEach((reciter) => {
      const cell = data.agreement[mushaf]?.[reciter.id]?.["ج"];
      if (cell?.[1]) {
        const rate = cell[0] / cell[1];
        lo = Math.min(lo, rate);
        hi = Math.max(hi, rate);
      }
    });
    return {lo, hi};
  }, [data, mushaf]);

  const openCases = (rid: string, mark: string) => {
    setCasesLoading(true);
    setShown(HIT_PAGE);
    const query = `mushaf=${encodeURIComponent(mushaf)}&reciter=${encodeURIComponent(rid)}&mark=${encodeURIComponent(mark)}`;
    getJson<AgreeCasesPayload>(`/backend-api/waqf-research/mushaf-agreement/cases?${query}`)
      .then((payload) => setCases({rid, mark, payload}))
      .catch(() => setError("تعذّر التحميل"))
      .finally(() => setCasesLoading(false));
  };

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!data) return <StatusState tone="loading">جارٍ تحليل وقوف القرّاء عبر المصحف كاملًا…</StatusState>;

  const selectedMark = (sym: string) => marks.find((mark) => mark.sym === sym);
  const reciterName = (id: string) => data.reciters.find((reciter) => reciter.id === id)?.name_ar || id;

  return (
    <div className="grid gap-3">
      <ToolBlurb
        shortText={`موافقة القرّاء لمصحف «${mushaf}». اضغط خلية أو شريطًا لعرض الآيات.`}
        longText="عمود ج = نسبة الوقف عند الجائز (ليس صوابًا/خطأً). الأعلى يعامله كقلى، الأدنى كصلى."
      />
      <div className="flex flex-wrap gap-1.5">
        {data.mushafs.map((name) => (
          <Button key={name} size="sm" variant={mushaf === name ? "primary" : "secondary"} onClick={() => { setMushaf(name); setCases(null); }}>
            {name}
          </Button>
        ))}
      </div>
      <details className="text-[0.82rem] text-athar-ink-soft">
        <summary className="cursor-pointer font-semibold">معنى الأعمدة</summary>
        <div className="mt-2 grid gap-1">
          {marks.map((mark) => (
            <span key={mark.sym}>
              <span className={cn(mushafFontClass(mushaf), "text-athar-accent")}>{mark.glyph}</span>
              {" "}<b>{mark.name}</b> — {agreeDesc(mark)}
              {mark.dir === "choice" ? ` (${toArabicDigits(data.jaiz[mushaf] || 0)} موضعًا)` : ""}
            </span>
          ))}
          {mushaf === "ورش" ? <span><b>صه</b> في الورش = «اصمت / قف هنا» — فالموافقة هنا أن يقف القارئ.</span> : null}
        </div>
      </details>
      <LabTable>
        <thead>
          <tr>
            <th>القارئ</th>
            {marks.map((mark) => (
              <th key={mark.sym} title={agreeDesc(mark)}>
                <span className={cn(mushafFontClass(mushaf), "text-athar-accent")}>{mark.glyph}</span>
                <span className="block text-[0.68rem] font-normal text-athar-ink-faint">{mark.name}<br />{agreeVerb(mark)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.reciters.map((reciter) => (
            <tr key={reciter.id}>
              <th className="text-start">
                {reciter.name_ar}
                {reciter.qasr ? <span className="ms-1 rounded-full bg-athar-line-soft px-1.5 text-[0.58rem]">قصر المنفصل</span> : null}
              </th>
              {marks.map((mark) => {
                const cell = data.agreement[mushaf]?.[reciter.id]?.[mark.sym];
                const value = pct(cell);
                if (value === null) return <td className="text-athar-ink-faint" key={mark.sym}>—</td>;
                if (mark.dir === "choice" && cell) {
                  const rate = cell[0] / cell[1];
                  const t = jaizRange.hi > jaizRange.lo ? (rate - jaizRange.lo) / (jaizRange.hi - jaizRange.lo) : 0.5;
                  const lean = t >= 0.6 ? "كقلى" : t <= 0.4 ? "كصلى" : "متوسط";
                  return (
                    <td key={mark.sym}>
                      <button
                        type="button"
                        className="w-full rounded-md px-1 py-1 text-white"
                        style={{background: `color-mix(in srgb, var(--wq-solo) ${Math.round(t * 100)}%, var(--wq-consensus, #16a34a))`}}
                        onClick={() => openCases(reciter.id, mark.sym)}
                      >
                        <b>{toArabicDigits(value)}٪</b>
                        <span className="block text-[0.62rem] opacity-80">{lean}</span>
                      </button>
                    </td>
                  );
                }
                const tone = value >= 80 ? "text-athar-waqf-consensus" : value >= 50 ? "text-athar-waqf-solo" : "text-athar-negative";
                return (
                  <td key={mark.sym}>
                    <button type="button" className={cn("w-full", tone)} onClick={() => openCases(reciter.id, mark.sym)}>
                      <b>{toArabicDigits(value)}٪</b>
                      <span className="block text-[0.62rem] text-athar-ink-faint">{toArabicDigits(cell?.[0] || 0)}/{toArabicDigits(cell?.[1] || 0)}</span>
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </LabTable>
      <LabNarrow className="gap-2">
        {data.reciters.map((reciter) => (
          <div className="grid gap-2 rounded-xl border border-athar-line px-3 py-2" key={reciter.id}>
            <b>{reciter.name_ar}</b>
            {marks.map((mark) => {
              const value = pct(data.agreement[mushaf]?.[reciter.id]?.[mark.sym]);
              if (value === null) return null;
              return (
                <button type="button" className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 text-start" onClick={() => openCases(reciter.id, mark.sym)} key={mark.sym}>
                  <span className={mushafFontClass(mushaf)}>{mark.glyph}</span>
                  <span className="h-1.5 overflow-hidden rounded-full bg-athar-line">
                    <span className="block h-full rounded-full bg-athar-accent" style={{width: `${value}%`}} />
                  </span>
                  <b className="tabular-nums">{toArabicDigits(value)}٪</b>
                </button>
              );
            })}
          </div>
        ))}
      </LabNarrow>
      {casesLoading ? <StatusState tone="loading">جارٍ الجلب…</StatusState> : null}
      {cases ? (
        <div className="grid gap-2">
          {(() => {
            const mark = selectedMark(cases.mark);
            const went = mark?.dir === "choice" ? "وقف عند" : mark?.dir === "stop" ? "لم يقف عند" : "وقف عند";
            if (!cases.payload.verses?.length) {
              return <StatusState>{mark?.dir === "choice" ? "لم يقف عند أيٍّ من مواضع الجائز." : "لا مخالفات — وافق العلامة في كل المواضع."}</StatusState>;
            }
            return (
              <>
                <p className="m-0 text-sm">
                  {reciterName(cases.rid)} — <b>{mark?.name || cases.mark}</b>: {went} العلامة في <b>{toArabicDigits(cases.payload.disagreed)}</b> موضعًا
                  {cases.payload.capped ? ` (عُرض أول ${toArabicDigits(cases.payload.shown || cases.payload.verses.length)})` : ""}
                </p>
                <HitList
                  items={cases.payload.verses}
                  shown={shown}
                  onShowMore={() => setShown((value) => value + HIT_PAGE)}
                  renderItem={(item) => (
                    <HitRow
                      occurrence={item}
                      hideMarks
                      surahName={surahs.find((surah) => surah.number === item.surah)?.name}
                      key={`${item.surah}:${item.ayah}`}
                    />
                  )}
                />
              </>
            );
          })()}
        </div>
      ) : null}
    </div>
  );
}

function Dendrogram({data}: {data: MushafSimPayload}) {
  if (!data.tree) return null;
  const placed = placedTree(data.tree, data.order || []);
  return (
    <LabWide className="overflow-x-auto">
      <svg viewBox={`0 0 ${placed.width} ${placed.height}`} className="h-auto w-full max-w-[600px]" role="img" aria-label="شجرة تقارب المصاحف">
        <g className="fill-none stroke-athar-line [stroke-width:1.4]">
          {placed.segments.map(([x1, y1, x2, y2], index) => (
            <line x1={x1} y1={y1} x2={x2} y2={y2} key={index} />
          ))}
        </g>
        {placed.forks.filter((node): node is Extract<typeof node, {type: "node"}> => node.type === "node").map((node, index) => (
          <g key={`fork-${index}`}>
            <circle className="fill-athar-surface stroke-athar-accent" cx={node._x} cy={node._y} r="13" />
            <text className="fill-athar-ink text-[11px]" x={node._x} y={node._y} dy="0.32em" textAnchor="middle">{toArabicDigits(Math.round(node.similarity * 100))}</text>
          </g>
        ))}
        {placed.leaves.filter((node): node is Extract<typeof node, {type: "leaf"}> => node.type === "leaf").map((leaf) => (
          <g key={leaf.id}>
            <circle className="fill-athar-surface stroke-athar-accent" cx={leaf._x} cy={leaf._y} r="3.5" />
            <text className="fill-athar-ink text-[11px]" x={placed.xLeaf + 12} y={leaf._y} dy="0.32em">
              {leaf.name}{data.counts?.[leaf.id] != null ? ` · ${toArabicDigits(data.counts[leaf.id])}` : ""}
            </text>
          </g>
        ))}
      </svg>
    </LabWide>
  );
}

export function LabMushafSimPanel({surahs}: {surahs: Surah[]}) {
  const [data, setData] = useState<MushafSimPayload | null>(null);
  const [view, setView] = useState<"overview" | "marks" | "profiles" | "compare">("overview");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
  const [diff, setDiff] = useState<MushafDiffPayload | null>(null);
  const [diffError, setDiffError] = useState("");
  const [diffLoading, setDiffLoading] = useState(false);
  const [error, setError] = useState("");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    const controller = new AbortController();
    getJson<MushafSimPayload>("/backend-api/waqf-research/mushaf-similarity", controller.signal)
      .then((payload) => {
        setData(payload);
        setLeft(payload.mushafs[0] || "");
        setRight(payload.mushafs[1] || "");
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  const runCompare = () => {
    if (!left || !right || left === right) {
      setDiff(null);
      setDiffError("اختر مصحفين مختلفين.");
      return;
    }
    setDiffError("");
    setDiffLoading(true);
    setShown(HIT_PAGE);
    getJson<MushafDiffPayload>(`/backend-api/waqf-research/mushaf-diff?a=${encodeURIComponent(left)}&b=${encodeURIComponent(right)}`)
      .then(setDiff)
      .catch(() => setDiffError("تعذّر التحميل"))
      .finally(() => setDiffLoading(false));
  };

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!data) return <StatusState tone="loading">جارٍ مقارنة أنظمة الوقف…</StatusState>;

  return (
    <div className="grid gap-3">
      <SegmentedControl
        variant="pills"
        className="h-auto w-fit flex-wrap"
        label="عرض تقارب المصاحف"
        value={view}
        options={[
          {value: "overview", label: "نظرة عامة"},
          {value: "marks", label: "التوافق لكل علامة"},
          {value: "profiles", label: "ما يميّز كل مصحف"},
          {value: "compare", label: "قارن مصحفين"},
        ]}
        onChange={setView}
      />
      {view === "overview" ? (
        <div className="grid gap-3">
          <ToolBlurb shortText="أقرب المصاحف في نظام الوقف — الشجرة على الشاشات الواسعة." />
          <span className="text-[0.78rem] font-bold text-athar-ink-soft">أقرب المصاحف بعضها لبعض</span>
          <div className="grid gap-2">
            {(data.pairs || []).slice(0, 12).map((pair) => (
              <div className="grid gap-1 rounded-xl border border-athar-line-soft px-3 py-2" key={`${pair.a}-${pair.b}`}>
                <div className="flex flex-wrap justify-between gap-2 text-sm">
                  <b>{pair.a} ↔ {pair.b}</b>
                  <span className="text-athar-ink-soft">{toArabicDigits(Math.round(pair.place * 100))}٪ موضعًا</span>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2">
                  <span className="h-1.5 overflow-hidden rounded-full bg-athar-line">
                    <span className="block h-full rounded-full bg-athar-accent" style={{width: `${Math.round(pair.meaning * 100)}%`}} />
                  </span>
                  <span className="text-[0.78rem] tabular-nums">{toArabicDigits(Math.round(pair.meaning * 100))}٪ حكمًا</span>
                </div>
              </div>
            ))}
          </div>
          <Dendrogram data={data} />
        </div>
      ) : null}
      {view === "marks" ? (
        <div className="grid gap-3">
          <p className="m-0 text-[0.86rem] leading-6 text-athar-ink-soft">
            لكل علامة وقف: كم موضعًا يَسِمه كل مصحف قياسي بها، ونسبة اتفاق المصاحف عند المواضع التي تحملها.
            <b> الأزهر</b> يوحّد قلى وصلى في «ج»، فأعمدته في «ق» و«ص» صفر. (ورش والهندي نظامان مختلفان — انظر «ما يميّز كل مصحف».)
          </p>
          <div className="grid gap-2">
            {(data.mark_consensus || []).map((mark) => (
              <div className="grid gap-2 rounded-xl border border-athar-line px-3 py-2.5" key={mark.sym}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-athar-quran text-xl text-athar-accent">{mark.glyph}</span>
                  <div className="min-w-0 flex-1">
                    <div className="font-bold">{waqfMarkLabel(mark.sym)} <small className="text-athar-ink-faint">({mark.sym})</small></div>
                    <div className="text-[0.78rem] text-athar-ink-soft">{mark.desc}</div>
                  </div>
                  <span className="text-[0.78rem] text-athar-ink-soft">{toArabicDigits(Math.round(mark.agreement * 100))}٪ اتفاق · {toArabicDigits(mark.positions)} موضعًا</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(data.standard || []).map((name) => (
                    <span className={cn("rounded-full border px-2 py-0.5 text-[0.72rem]", mark.counts[name] ? "border-athar-line" : "border-dashed text-athar-ink-faint")} key={name}>
                      <b>{toArabicDigits(mark.counts[name] || 0)}</b> {name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {view === "profiles" ? (
        <div className="grid gap-3">
          <p className="m-0 text-[0.86rem] text-athar-ink-soft">ما الذي يميّز كل مصحف؟ سطورٌ مستخلصة آليًّا من مقارنة علاماته ببقيّة المصاحف.</p>
          <div className="grid gap-3 md:grid-cols-2">
            {(data.order || data.mushafs).map((id) => {
              const profile = (data.profiles || []).find((item) => item.id === id);
              if (!profile) return null;
              return (
                <article className="grid gap-2 rounded-xl border border-athar-line p-3" key={id}>
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <strong>{id}</strong>
                    <span className="text-[0.72rem] text-athar-ink-faint">{SYSTEM_LABEL[profile.system] || ""}</span>
                  </div>
                  <span className="text-sm text-athar-accent">{toArabicDigits(profile.total)} موضع وقف</span>
                  <ul className="m-0 grid list-disc gap-1 ps-5 text-[0.82rem] text-athar-ink-soft">
                    {(profile.special.length ? profile.special : ["يتبع النظام القياسي دون تفرّدٍ بارز."]).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  <div className="flex flex-wrap gap-1.5">
                    {(data.marks || []).filter((mark) => profile.counts[mark]).map((mark) => (
                      <span className="rounded-full border border-athar-line px-2 py-0.5 text-[0.72rem]" key={mark}>
                        <b>{toArabicDigits(profile.counts[mark])}</b> {mushafGlyph(mark, id)}
                      </span>
                    ))}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      ) : null}
      {view === "compare" ? (
        <div className="grid gap-3">
          <p className="m-0 text-[0.86rem] text-athar-ink-soft">اختر مصحفين لعرض كل كلمة اختلفا في حكم الوقف عليها (اضغط أي كلمة لفتح آيتها).</p>
          <div className="flex flex-wrap items-end gap-2">
            <ChromeField label="المصحف الأول">
              <ChromeSelect value={left} onChange={(event) => setLeft(event.target.value)}>
                {data.mushafs.map((name) => <option key={name} value={name}>{name}</option>)}
              </ChromeSelect>
            </ChromeField>
            <span className="pb-3 text-sm text-athar-ink-soft">مقابل</span>
            <ChromeField label="المصحف الثاني">
              <ChromeSelect value={right} onChange={(event) => setRight(event.target.value)}>
                {data.mushafs.map((name) => <option key={name} value={name}>{name}</option>)}
              </ChromeSelect>
            </ChromeField>
            <Button className="self-end" onClick={runCompare}>قارن</Button>
          </div>
          {diffLoading ? <StatusState tone="loading">جارٍ المقارنة…</StatusState> : null}
          {diffError ? <StatusState tone="error">{diffError}</StatusState> : null}
          {diff ? (
            <div className="grid gap-3">
              <p className="m-0 text-sm">
                <b>{diff.a}</b> و<b>{diff.b}</b> يتفقان حكمًا بنسبة <b>{toArabicDigits(Math.round(diff.meaning * 100))}٪</b>،
                ويختلفان في <b>{toArabicDigits(diff.differences)}</b> موضعًا
                {diff.capped ? ` (عُرض أول ${toArabicDigits(diff.shown)})` : ""}.
              </p>
              <div className="flex flex-wrap gap-2 text-[0.78rem]">
                <span className="text-athar-accent">{diff.a}</span>
                <span>·</span>
                <span className="text-athar-waqf-solo">{diff.b}</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {diff.groups.map((group) => (
                  <span className="inline-flex items-center gap-1 rounded-full border border-athar-line px-2 py-0.5 text-[0.78rem]" key={`${group.a_sym}-${group.b_sym}`}>
                    <span className={mushafFontClass(diff.a)}>{mushafGlyph(group.a_sym, diff.a) || "بلا"}</span>
                    ↔
                    <span className={mushafFontClass(diff.b)}>{mushafGlyph(group.b_sym, diff.b) || "بلا"}</span>
                    <b>{toArabicDigits(group.count)}</b>
                  </span>
                ))}
              </div>
              <HitList
                items={diff.verses}
                shown={shown}
                onShowMore={() => setShown((value) => value + HIT_PAGE)}
                empty="لا اختلاف بينهما في الحكم."
                renderItem={(item, index) => (
                  <HitRow
                    occurrence={item}
                    hideMarks
                    editorEditions={[diff.a, diff.b].filter((edition) => edition === "قطر" || edition === "الكويت" || edition === "البحرين")}
                    surahName={surahs.find((surah) => surah.number === item.surah)?.name}
                    marks={(
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={cn(mushafFontClass(diff.a), "text-athar-accent")}>{mushafGlyph(item.a_sym, diff.a) || "بلا"}</span>
                        <HitChip muted>↔</HitChip>
                        <span className={cn(mushafFontClass(diff.b), "text-athar-waqf-solo")}>{mushafGlyph(item.b_sym, diff.b) || "بلا"}</span>
                      </div>
                    )}
                    key={`${item.surah}:${item.ayah}:${index}`}
                  />
                )}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
