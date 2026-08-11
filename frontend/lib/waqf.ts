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
