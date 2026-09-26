export type ToolKey = "waqf" | "lab" | "practice" | "read" | "memorize";

export type ToolEntry = {
  key: ToolKey;
  /** Short nav label. */
  label: string;
  /** Full name used on cards and in the command palette. */
  title: string;
  /** Imperative verb for the step the tool represents. */
  verb: string;
  description: string;
};

export type VerseContext = {surah: number; ayah: number};

/** الوقف والابتداء — Athar's core. Ordered as the learning path: observe → search → practise. */
export const waqfTools: ToolEntry[] = [
  {
    key: "waqf",
    label: "مُكْث",
    title: "دليل الوقف",
    verb: "تأمّل",
    description: "لكل موضع ثلاث شهادات: علامة المصاحف، ووقف القرّاء، وحكم أئمة الوقف — ثم اختر ما يناسب نَفَسك.",
  },
  {
    key: "lab",
    label: "المختبر",
    title: "مختبر الوقف",
    verb: "ابحث",
    description: "ادرس الوقف عبر القرآن كله: كلمات وأنماط، وانفرادات القرّاء، واختلاف المصاحف.",
  },
  {
    key: "practice",
    label: "تدريب",
    title: "تدريب الوقف",
    verb: "تدرّب",
    description: "علّم أين تقف في مقطع، ثم قارن وقوفك بعلامات المصاحف المطبوعة.",
  },
];

/** Reading and memorisation support the waqf work. */
export const supportTools: ToolEntry[] = [
  {
    key: "read",
    label: "المصحف",
    title: "المصحف",
    verb: "اقرأ",
    description: "رسم قريب من المطبوع، وموضعك محفوظ، والتفسير والتلاوة عند الحاجة.",
  },
  {
    key: "memorize",
    label: "تثبيت",
    title: "تثبيت",
    verb: "احفظ",
    description: "المصحف يملأ الشاشة: كرّر وأخفِ على الصفحة نفسها حتى يثبت المقطع.",
  },
];

export const allTools = [...waqfTools, ...supportTools];

const toolPaths: Record<ToolKey, string> = {
  waqf: "/waqf",
  lab: "/waqf-lab",
  practice: "/waqf-practice",
  read: "/read",
  memorize: "/memorize",
};

export function toolPath(key: ToolKey) {
  return toolPaths[key];
}

/** Link to a tool, opened on the given ayah when the tool is ayah-based. */
export function toolHref(key: ToolKey, context?: VerseContext | null) {
  const path = toolPaths[key];
  if (!context || key === "lab") return path;
  const {surah, ayah} = context;
  if (key === "practice" || key === "memorize") return `${path}?surah=${surah}&from=${ayah}&to=${ayah}`;
  return `${path}?surah=${surah}&ayah=${ayah}`;
}

export function labWordHref(query: string) {
  return `/waqf-lab?tab=word&family=words&q=${encodeURIComponent(query)}`;
}

export function isToolPath(pathname: string, key: ToolKey) {
  const path = toolPaths[key];
  return pathname === path || pathname.startsWith(`${path}/`);
}

/** The ayah the current page is on, read from the tools' shared URL params. */
export function verseContextFrom(params: URLSearchParams | {get(name: string): string | null}): VerseContext | null {
  const surah = Number(params.get("surah"));
  const ayah = Number(params.get("ayah") || params.get("from"));
  if (!Number.isInteger(surah) || surah < 1 || surah > 114) return null;
  return {surah, ayah: Number.isInteger(ayah) && ayah >= 1 ? ayah : 1};
}
