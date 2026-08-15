"use client";

import {useEffect, useMemo, useState} from "react";
import {getJson, type Surah} from "@/lib/api";
import {toArabicDigits} from "@/lib/mushaf";
import {Button, ProgressBar, SegmentedControl, StatTile, StatusState} from "@/components/ui/primitives";
import {CountLabel, HitList, HitRow, LabNarrow, LabTable, LabWide, ToneChip, ToolBlurb} from "@/components/waqf-lab-hit";
import {HIT_PAGE, type ClusterPayload, type ResearchOccurrence, type SoloDetail, type SoloSummary, type StatsSurah, type StatsVerse} from "@/lib/waqf-lab";

function clusterHeat(sim: number, lo: number, hi: number, self: boolean) {
  if (self) return {background: "var(--athar-accent)", color: "var(--athar-on-accent)"};
  const t = hi > lo ? Math.max(0, Math.min(1, (sim - lo) / (hi - lo))) : 0.5;
  return {
    background: `color-mix(in srgb, var(--athar-accent) ${Math.round((0.08 + t * 0.92) * 100)}%, transparent)`,
    color: t > 0.6 ? "var(--athar-on-accent)" : "var(--athar-ink)",
  };
}

export function LabSolosPanel({surahs}: {surahs: Surah[]}) {
  const [summary, setSummary] = useState<SoloSummary[] | null>(null);
  const [detail, setDetail] = useState<SoloDetail | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"" | "yes" | "no">("");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    const controller = new AbortController();
    getJson<{reciters: SoloSummary[]}>("/backend-api/waqf-research/solos", controller.signal)
      .then((payload) => setSummary([...(payload.reciters || [])].sort((a, b) => b.solo_count - a.solo_count)))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  const openReciter = (id: string) => {
    setError("");
    setFilter("");
    setShown(HIT_PAGE);
    getJson<SoloDetail>(`/backend-api/waqf-research/solos?reciter=${encodeURIComponent(id)}`)
      .then(setDetail)
      .catch(() => setError("تعذّر التحميل"));
  };

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!summary) return <StatusState tone="loading">جارٍ التحليل…</StatusState>;

  if (detail) {
    const stops = detail.stops || [];
    const withMark = stops.filter((item) => item.has_waqf).length;
    const list = filter === "yes" ? stops.filter((item) => item.has_waqf) : filter === "no" ? stops.filter((item) => !item.has_waqf) : stops;
    return (
      <div className="grid gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => setDetail(null)}>← كل القرّاء</Button>
          <strong>{detail.reciter.name_ar}</strong>
          <CountLabel>{toArabicDigits(stops.length)} انفراد</CountLabel>
        </div>
        {withMark && withMark < stops.length ? (
          <SegmentedControl
            variant="pills"
            className="h-auto w-fit flex-wrap"
            label="الوقف المطبوع"
            value={filter || "all"}
            options={[
              {value: "all", label: "الكل"},
              {value: "yes", label: `يوافق مصحفًا ${toArabicDigits(withMark)}`},
              {value: "no", label: `بلا علامة ${toArabicDigits(stops.length - withMark)}`},
            ]}
            onChange={(value) => {
              setFilter(value === "all" ? "" : value);
              setShown(HIT_PAGE);
            }}
          />
        ) : null}
        <HitList
          items={list}
          shown={shown}
          onShowMore={() => setShown((value) => value + HIT_PAGE)}
          renderItem={(item: ResearchOccurrence) => (
            <HitRow
              occurrence={item}
              surahName={surahs.find((surah) => surah.number === item.surah)?.name}
              key={`${item.surah}:${item.ayah}:${item.wpos}`}
            />
          )}
        />
      </div>
    );
  }

  const maxSolo = Math.max(...summary.map((item) => item.solo_count), 1);
  return (
    <div className="grid gap-3">
      <ToolBlurb shortText="مواضع وقف انفرد بها كل قارئ دون بقية القرّاء." />
      <div className="grid gap-1.5">
        {summary.map((reciter) => (
          <button
            type="button"
            className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-athar-line bg-athar-surface px-3 py-2 text-start hover:border-athar-accent"
            onClick={() => openReciter(reciter.id)}
            key={reciter.id}
          >
            <span className="grid gap-1">
              <span className="font-bold">{reciter.name_ar}</span>
              <ProgressBar value={reciter.solo_count} max={maxSolo} label={`${reciter.name_ar}: ${toArabicDigits(reciter.solo_count)}`} />
            </span>
            <b className="text-athar-accent tabular-nums">{toArabicDigits(reciter.solo_count)}</b>
          </button>
        ))}
      </div>
    </div>
  );
}

export function LabStatsPanel({surahs}: {surahs: Surah[]}) {
  const [view, setView] = useState<"surahs" | "verses" | "consensus">("surahs");
  const [stats, setStats] = useState<{surahs: StatsSurah[]; top_divergent: StatsVerse[]} | null>(null);
  const [consensus, setConsensus] = useState<ResearchOccurrence[] | null>(null);
  const [error, setError] = useState("");
  const [shown, setShown] = useState(HIT_PAGE);

  useEffect(() => {
    const controller = new AbortController();
    getJson<{surahs: StatsSurah[]; top_divergent: StatsVerse[]}>("/backend-api/waqf-research/stats", controller.signal)
      .then(setStats)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (view !== "consensus" || consensus) return;
    getJson<{consensus: ResearchOccurrence[]}>("/backend-api/waqf-research/stats?view=consensus")
      .then((payload) => setConsensus(payload.consensus || []))
      .catch(() => setError("تعذّر التحميل"));
  }, [view, consensus]);

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!stats) return <StatusState tone="loading">جارٍ التحليل…</StatusState>;

  const totalDiv = stats.surahs.reduce((sum, item) => sum + item.divergent, 0);
  const totalCons = stats.surahs.reduce((sum, item) => sum + item.consensus, 0);
  const surahsList = [...stats.surahs].filter((item) => item.total > 0).sort((a, b) => b.divergent - a.divergent);
  const verses = (stats.top_divergent || []).slice(0, 80);

  return (
    <div className="grid gap-3">
      <div className="grid grid-cols-2 gap-2">
        <StatTile label="موضع اختلاف" value={toArabicDigits(totalDiv)} />
        <StatTile label="موضع اتفاق تام" value={toArabicDigits(view === "consensus" ? (consensus?.length || totalCons) : totalCons)} />
      </div>
      <SegmentedControl
        variant="pills"
        className="h-auto w-fit flex-wrap"
        label="عرض الإحصائيات"
        value={view}
        options={[
          {value: "surahs", label: "السور"},
          {value: "verses", label: "أكثر الآيات اختلافًا"},
          {value: "consensus", label: "مواضع الاتفاق"},
        ]}
        onChange={(value) => {
          setView(value);
          setShown(HIT_PAGE);
        }}
      />
      {view === "surahs" ? (
        <div className="grid gap-1.5">
          {surahsList.map((item) => {
            const pct = item.total ? Math.round((item.consensus / item.total) * 100) : 0;
            return (
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-athar-line-soft px-3 py-2" key={item.surah}>
                <span className="grid gap-1">
                  <span className="text-sm font-bold">{item.name} <b className="text-athar-accent">{toArabicDigits(item.surah)}</b></span>
                  <ProgressBar value={pct} max={100} label={`${item.name}: ${toArabicDigits(pct)}٪ اتفاق`} />
                </span>
                <span className="text-[0.78rem] tabular-nums text-athar-ink-soft">
                  <span className="text-athar-waqf-consensus">{toArabicDigits(item.consensus)}</span>
                  {" / "}
                  <span className="text-athar-waqf-solo">{toArabicDigits(item.divergent)}</span>
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
      {view === "verses" ? (
        <HitList
          items={verses}
          shown={shown}
          onShowMore={() => setShown((value) => value + HIT_PAGE)}
          renderItem={(item) => (
            <HitRow
              occurrence={item}
              hideMarks
              surahName={surahs.find((surah) => surah.number === item.surah)?.name}
              meta={(
                <>
                  <ToneChip tone="solo">{toArabicDigits(item.divergent)} اختلاف</ToneChip>
                  <ToneChip tone="accent">{toArabicDigits(item.consensus)} اتفاق</ToneChip>
                </>
              )}
              key={`${item.surah}:${item.ayah}`}
            />
          )}
        />
      ) : null}
      {view === "consensus" ? (
        consensus ? (
          <div className="grid gap-3">
            <ToolBlurb shortText="مواضع اتفق عليها جميع القرّاء ولها علامة مطبوعة." />
            <CountLabel>{toArabicDigits(consensus.length)} موضعًا</CountLabel>
            <HitList
              items={consensus}
              shown={shown}
              onShowMore={() => setShown((value) => value + HIT_PAGE)}
              renderItem={(item) => (
                <HitRow
                  occurrence={item}
                  editorEditions={[]}
                  surahName={surahs.find((surah) => surah.number === item.surah)?.name}
                  meta={<ToneChip tone="consensus">كلهم</ToneChip>}
                  key={`${item.surah}:${item.ayah}:${item.wpos}`}
                />
              )}
            />
          </div>
        ) : <StatusState tone="loading">جارٍ التحميل…</StatusState>
      ) : null}
    </div>
  );
}

export function LabClusterPanel() {
  const [data, setData] = useState<ClusterPayload | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getJson<ClusterPayload>("/backend-api/waqf-research/clustering", controller.signal)
      .then(setData)
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError("تعذّر التحميل");
      });
    return () => controller.abort();
  }, []);

  const groups = useMemo(() => (data?.clusters || []).filter((item) => item.size > 1), [data]);
  const singles = useMemo(
    () => (data?.clusters || []).filter((item) => item.size === 1).flatMap((item) => item.members.map((member) => member.name_ar)),
    [data],
  );

  if (error) return <StatusState tone="error">{error}</StatusState>;
  if (!data) return <StatusState tone="loading">جارٍ التحليل…</StatusState>;

  const order = data.order || [];
  const lo = data.range.min;
  const hi = data.range.max;
  const different = (data.different || []).slice(0, 6);
  const alike = (data.similar || data.closest || []).slice(0, 6);

  return (
    <div className="grid gap-4">
      <ToolBlurb
        shortText="تشابه أنماط الوقف بين القرّاء (جاكار)."
        longText="القرّاء مرتّبون بحيث يتجاور المتشابهون. على الشاشات الصغيرة تُعرض المجموعات والأزواج بدل شبكة الألوان."
      />
      <div className="grid gap-2">
        {groups.map((group, index) => (
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-athar-line-soft px-3 py-2" key={index}>
            <span className="text-[0.72rem] font-bold text-athar-accent">المجموعة {toArabicDigits(index + 1)} · تماسك {toArabicDigits(Math.round(group.cohesion * 100))}٪</span>
            {group.members.map((member) => (
              <ToneChip tone="accent" className="text-[0.78rem] font-semibold" key={member.id}>{member.name_ar}</ToneChip>
            ))}
          </div>
        ))}
        {singles.length ? (
          <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-dashed border-athar-line px-3 py-2">
            <span className="text-[0.72rem] font-bold text-athar-ink-faint">قرّاء متفرّدون</span>
            {singles.map((name) => <ToneChip key={name}>{name}</ToneChip>)}
          </div>
        ) : null}
      </div>
      <LabTable>
        <thead>
          <tr>
            <th />
            {order.map((item, index) => <th key={item.id} title={item.name_ar}>{toArabicDigits(index + 1)}</th>)}
          </tr>
        </thead>
        <tbody>
          {order.map((row, rowIndex) => (
            <tr key={row.id}>
              <th className="text-start font-semibold">
                <span className="me-1 text-athar-ink-faint">{toArabicDigits(rowIndex + 1)}</span>
                {row.name_ar}
                {row.qasr ? <span className="ms-1 text-[0.62rem] text-athar-ink-faint">قصر</span> : null}
              </th>
              {order.map((col, colIndex) => {
                const sim = data.matrix[row.id]?.[col.id] ?? 0;
                return (
                  <td key={col.id} style={clusterHeat(sim, lo, hi, rowIndex === colIndex)} title={`${row.name_ar} × ${col.name_ar}: ${toArabicDigits(Math.round(sim * 100))}٪`}>
                    {rowIndex === colIndex ? "" : toArabicDigits(Math.round(sim * 100))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </LabTable>
      <LabWide className="grid gap-2">
        <span className="text-[0.78rem] font-bold text-athar-ink-soft">أبعد القرّاء تشابهًا</span>
        <div className="flex flex-wrap gap-2">
          {different.map((pair) => (
            <span className="rounded-xl border border-athar-line px-2.5 py-1 text-[0.8rem]" key={`${pair.n1}-${pair.n2}`}>
              <b className="text-athar-accent">{toArabicDigits(Math.round(pair.similarity * 100))}٪</b> {pair.n1} ↔ {pair.n2}
            </span>
          ))}
        </div>
      </LabWide>
      <LabNarrow className="gap-2">
        <span className="text-[0.78rem] font-bold text-athar-ink-soft">أبعد القرّاء تشابهًا</span>
        {different.map((pair) => (
          <div className="flex items-center justify-between rounded-xl border border-athar-line px-3 py-2" key={`${pair.n1}-${pair.n2}`}>
            <b>{pair.n1} ↔ {pair.n2}</b>
            <span>{toArabicDigits(Math.round(pair.similarity * 100))}٪</span>
          </div>
        ))}
        {alike.length ? (
          <>
            <span className="text-[0.78rem] font-bold text-athar-ink-soft">أقرب القرّاء</span>
            {alike.map((pair) => (
              <div className="flex items-center justify-between rounded-xl border border-athar-line px-3 py-2" key={`${pair.n1}-${pair.n2}`}>
                <b>{pair.n1} ↔ {pair.n2}</b>
                <span>{toArabicDigits(Math.round(pair.similarity * 100))}٪</span>
              </div>
            ))}
          </>
        ) : null}
      </LabNarrow>
    </div>
  );
}
