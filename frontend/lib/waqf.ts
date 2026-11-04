import type {WaqfPhrase, WaqfReciterDetail} from "@/lib/api";

export type WaqfMarkTone = "strong" | "avoid" | "neutral";

const markDescriptions: Record<string, {label: string; guidance: string; tone: WaqfMarkTone}> = {
  "م": {label: "وقف لازم", guidance: "قف هنا", tone: "strong"},
  "ق": {label: "الوقف أولى", guidance: "الوقف أنسب", tone: "strong"},
  "ج": {label: "وقف جائز", guidance: "يجوز الوقف والوصل", tone: "neutral"},
  "ص": {label: "الوصل أولى", guidance: "الوصل أنسب", tone: "neutral"},
  "لا": {label: "لا وقف", guidance: "لا تقف هنا", tone: "avoid"},
  "ع": {label: "وقف المعانقة", guidance: "قف على أحد الموضعين", tone: "neutral"},
  "س": {label: "سكتة", guidance: "اسكت بلا تنفّس", tone: "neutral"},
  "ركوع": {label: "علامة ركوع", guidance: "نهاية مقطع موضوعي", tone: "neutral"},
};

const markAliases: Record<string, string> = {
  "قلى": "ق",
  "قلي": "ق",
  "صلى": "ص",
  "صلي": "ص",
  "ۘ": "م",
  "ۗ": "ق",
  "ۖ": "ص",
  "ۚ": "ج",
  "ۙ": "لا",
  "ۜ": "س",
  "ۛ": "ع",
};

const uthmanicGlyphs: Record<string, string> = {
  "م": "ۘ",
  "ق": "ۗ",
  "قلى": "ۗ",
  "قلي": "ۗ",
  "ص": "ۖ",
  "صلى": "ۖ",
  "صلي": "ۖ",
  "ج": "ۚ",
  "لا": "ۙ",
  "س": "ۜ",
  "ع": "ۛ",
  "ؕ": "ؕ",
  "ؗ": "ؗ",
  "ؔ": "ؔ",
  "۪": "۪",
  "۫": "۫",
  "۬": "۬",
  "ۘ": "ۘ",
  "ۗ": "ۗ",
  "ۖ": "ۖ",
  "ۚ": "ۚ",
  "ۙ": "ۙ",
  "ۜ": "ۜ",
  "ۛ": "ۛ",
};

export const commonWaqfMarks = ["م", "لا", "ج", "ق"] as const;

/** The printed Hafs stop marks, strongest stop first, for legends. */
export const waqfMarkGuide = (["م", "ق", "ج", "ص", "لا", "ع", "س"] as const).map((symbol) => ({
  symbol,
  glyph: uthmanicGlyphs[symbol],
  ...markDescriptions[symbol],
}));

export const WAQF_SOURCES = ["المدينة الجديد", "المدينة القديم", "الأزهر", "الشمرلي"] as const;
export type WaqfSource = (typeof WAQF_SOURCES)[number];

export function isWaqfSource(value: string | null): value is WaqfSource {
  return value !== null && (WAQF_SOURCES as readonly string[]).includes(value);
}

export function waqfMarkCanonical(symbol: string) {
  const trimmed = symbol.replace(/\s+/g, "").trim();
  if (!trimmed) return "";
  if (markAliases[trimmed]) return markAliases[trimmed];
  const first = trimmed.split(/[،,]/)[0] || trimmed;
  return markAliases[first] || first;
}

export function majorityWaqfSymbol(symbols: string[]): string | null {
  const counts = new Map<string, number>();
  for (const symbol of symbols) {
    const canonical = waqfMarkCanonical(symbol);
    if (!canonical) continue;
    counts.set(canonical, (counts.get(canonical) || 0) + 1);
  }
  if (counts.size < 2) return null;
  let best: string | null = null;
  let bestCount = 0;
  let tied = false;
  for (const [canonical, count] of counts) {
    if (count > bestCount) {
      best = canonical;
      bestCount = count;
      tied = false;
    } else if (count === bestCount) {
      tied = true;
    }
  }
  return tied ? null : best;
}

export function waqfMarkDescription(symbol: string) {
  const canonical = waqfMarkCanonical(symbol) || symbol;
  return markDescriptions[canonical] || {
    label: "علامة وقف",
    guidance: "راجع حكم الموضع",
    tone: "neutral" as const,
  };
}

export function waqfMarkLabel(symbol: string) {
  return waqfMarkDescription(symbol).label;
}

export function waqfMarkTone(symbol: string) {
  return waqfMarkDescription(symbol).tone;
}

export function waqfMarkGlyph(symbol: string) {
  if (symbol === "ركوع") return symbol;
  return symbol
    .split(/[،,]/)
    .map((token) => token.replace(/\s+/g, "").trim())
    .filter(Boolean)
    .map((token) => {
      const canonical = markAliases[token] || token;
      return uthmanicGlyphs[canonical] || token;
    })
    .join("");
}

export function waqfOverlayGlyph(symbol: string) {
  return waqfMarkGlyph(symbol);
}

export function reciterPhrases(detail: WaqfReciterDetail, lastWpos: number): WaqfPhrase[] {
  if (detail.phrases?.length) return detail.phrases;
  const stops = [...detail.stops].sort((a, b) => a.wpos - b.wpos);
  const phrases = stops.map((stop, index) => ({
    first_wpos: index === 0 ? 0 : stops[index - 1].wpos + 1,
    last_wpos: stop.wpos,
    start: index === 0 ? 0 : stops[index - 1].time,
    end: stop.time,
  }));
  phrases.push({
    first_wpos: stops.length ? stops[stops.length - 1].wpos + 1 : 0,
    last_wpos: lastWpos,
    start: stops.length ? stops[stops.length - 1].time : 0,
    end: detail.duration,
  });
  return phrases;
}

/** Classical grades that rule a stop out rather than in. */
export function isNegativeGrade(grade: string) {
  return grade === "لا" || grade === "قبيح";
}

/** Grades that rule a stop in firmly (a stop the reader can start again from). */
const FIRM_GRADES = new Set(["تام", "كاف", "لازم", "صالح", "جيد", "بيان"]);

/** Which way a witness leans: 1 stop, -1 connect, 0 allows both, null = no evidence. */
export type WaqfLean = 1 | 0 | -1 | null;

export type WaqfVerdict = {
  tone: "stop" | "connect" | "split" | "open";
  text: string;
  witnesses: Array<{key: "mushaf" | "reciters" | "imams"; label: string; lean: WaqfLean}>;
};

export function printLean(symbol: string | null): WaqfLean {
  if (!symbol) return null;
  const canonical = waqfMarkCanonical(symbol);
  if (canonical === "م" || canonical === "ق") return 1;
  if (canonical === "ص" || canonical === "لا") return -1;
  if (canonical === "ج") return 0;
  return null;
}

export function readersLean(stopped: number, total: number): WaqfLean {
  if (!total) return null;
  const ratio = stopped / total;
  if (ratio >= 0.6) return 1;
  if (ratio <= 0.25) return -1;
  return 0;
}

export function imamsLean(grades: string[]): WaqfLean {
  if (!grades.length) return null;
  const negative = grades.some(isNegativeGrade);
  const firm = grades.some((grade) => FIRM_GRADES.has(grade));
  if (negative && firm) return 0;
  if (negative) return -1;
  return firm ? 1 : 0;
}

/**
 * One-line summary of the three witnesses for a stop. It only says «الأرجح» when
 * two witnesses lean the same way and none leans against them.
 */
export function waqfVerdict(witnesses: WaqfVerdict["witnesses"]): WaqfVerdict | null {
  const known = witnesses.filter((item) => item.lean !== null);
  if (!known.length) return null;
  const stop = known.filter((item) => item.lean === 1).length;
  const connect = known.filter((item) => item.lean === -1).length;
  const names = (lean: WaqfLean) => known.filter((item) => item.lean === lean).map((item) => item.label).join(" و");
  if (stop && connect) {
    return {tone: "split", text: `موضع خلاف: ${names(1)} تميل إلى الوقف، و${names(-1)} إلى الوصل`, witnesses};
  }
  if (stop >= 2) return {tone: "stop", text: "الأرجح: الوقف", witnesses};
  if (connect >= 2) return {tone: "connect", text: "الأرجح: الوصل", witnesses};
  if (stop) return {tone: "stop", text: `يميل إلى الوقف عند ${names(1)}`, witnesses};
  if (connect) return {tone: "connect", text: `يميل إلى الوصل عند ${names(-1)}`, witnesses};
  return {tone: "open", text: "الوقف والوصل جائزان", witnesses};
}

export const classicalGradeMeta: Record<string, {cls: string; desc: string}> = {
  "تام": {cls: "tamm", desc: "وقفٌ تام — يُوقف عليه ويُبتدأ بما بعده"},
  "كاف": {cls: "kafi", desc: "وقفٌ كافٍ — يُوقف عليه، وما بعده متعلقٌ به معنًى"},
  "حسن": {cls: "hasan", desc: "وقفٌ حسن — يَحسُن الوقف ولا يَحسُن الابتداء بما بعده"},
  "جائز": {cls: "jaiz", desc: "وقفٌ جائز"},
  "صالح": {cls: "kafi", desc: "وقفٌ صالح"},
  // النحاس's own kinds (القطع والائتناف counts eight: التام، التمام، الكافي، الحسن، الصالح، الجيد، البيان، القبيح)
  "جيد": {cls: "hasan", desc: "وقفٌ جيد — من أقسام الوقف عند النحاس"},
  "بيان": {cls: "jaiz", desc: "وقف بيان — يُوقف عليه لبيان المعنى"},
  "قبيح": {cls: "qabih", desc: "وقفٌ قبيح — لا يُوقف عليه"},
  "لا": {cls: "qabih", desc: "ليس بوقف"},
  "لازم": {cls: "tamm", desc: "وقفٌ لازم"},
};

export function tawjihSpanCoversWpos(
  entry: {wpos: number; wpos_start?: number | null},
  wpos: number,
): boolean {
  const start = Number.isFinite(entry.wpos_start) ? Number(entry.wpos_start) : entry.wpos;
  return wpos >= start && wpos <= entry.wpos;
}
