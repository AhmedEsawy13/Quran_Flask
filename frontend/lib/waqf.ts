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
  "ص": "ۖ",
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

export function waqfMarkDescription(symbol: string) {
  const canonical = markAliases[symbol] || symbol;
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

export const classicalGradeMeta: Record<string, {cls: string; desc: string}> = {
  "تام": {cls: "tamm", desc: "وقفٌ تام — يُوقف عليه ويُبتدأ بما بعده"},
  "كاف": {cls: "kafi", desc: "وقفٌ كافٍ — يُوقف عليه، وما بعده متعلقٌ به معنًى"},
  "حسن": {cls: "hasan", desc: "وقفٌ حسن — يَحسُن الوقف ولا يَحسُن الابتداء بما بعده"},
  "جائز": {cls: "jaiz", desc: "وقفٌ جائز"},
  "صالح": {cls: "kafi", desc: "وقفٌ صالح"},
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
