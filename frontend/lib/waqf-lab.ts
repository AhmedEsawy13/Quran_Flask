import {legacyUrl} from "@/lib/paths";
import {waqfMarkGlyph} from "@/lib/waqf";

export const HIT_PAGE = 40;

export type LabFamily = "words" | "reciters" | "mushafs";
export type LabTab =
  | "word"
  | "ibtidaa"
  | "saktat"
  | "mandatory"
  | "solos"
  | "stats"
  | "cluster"
  | "patterns"
  | "agreement"
  | "mushafsim";

/** Every tool, with the plain question it answers — the entry point for newcomers. */
export const LAB_TABS: Array<{id: LabTab; family: LabFamily; label: string; question: string}> = [
  {id: "word", family: "words", label: "بحث بالكلمة", question: "أين يُوقف على كلمةٍ ما في القرآن كله؟"},
  {id: "ibtidaa", family: "words", label: "الابتداء بما قبله", question: "أين وقف القارئ ثم رجع يبتدئ بكلمة قبلها؟"},
  {id: "saktat", family: "words", label: "السكتات", question: "أين يسكت حفص سكتةً يسيرة بلا تنفّس؟"},
  {id: "mandatory", family: "words", label: "اللازم والممنوع والمعانقة", question: "أين يلزم الوقف، وأين يُمنع، وأين يتعانق موضعان؟"},
  {id: "solos", family: "reciters", label: "انفرادات القرّاء", question: "أين وقف قارئ وحده دون بقية القرّاء؟"},
  {id: "stats", family: "reciters", label: "اتفاق القرّاء", question: "أيّ السور والآيات اتفق فيها القرّاء أو اختلفوا؟"},
  {id: "cluster", family: "reciters", label: "تشابه القرّاء", question: "أيّ القرّاء أقرب بعضهم إلى بعض في مواضع الوقف؟"},
  {id: "patterns", family: "mushafs", label: "اختلاف المصاحف", question: "أين اختلفت المصاحف في علامة الوقف على الكلمة نفسها؟"},
  {id: "agreement", family: "mushafs", label: "القرّاء والمصاحف", question: "هل يقف القرّاء حيث تضع المصاحف علاماتها؟"},
  {id: "mushafsim", family: "mushafs", label: "تقارب المصاحف", question: "أيّ المصاحف أقرب بعضها إلى بعض في نظام الوقف؟"},
];

export const LAB_FAMILIES: Array<{id: LabFamily; title: string; sub: string; description: string}> = [
  {id: "words", title: "كلمات وأنماط", sub: "بحث", description: "ابحث عن كلمة أو ظاهرة في القرآن كله."},
  {id: "reciters", title: "قرّاء", sub: "أداء", description: "كيف وقف القرّاء المتقنون في تلاواتهم."},
  {id: "mushafs", title: "مصاحف", sub: "طبع", description: "كيف وضعت المصاحف المطبوعة علامات الوقف."},
];

export function labTool(id: LabTab) {
  return LAB_TABS.find((item) => item.id === id) || LAB_TABS[0];
}

export const WORD_PRESETS: Array<{
  group: string;
  items: Array<{word: string; exact?: boolean; mode?: "before"}>;
}> = [
  {
    group: "حروف الردع والجواب",
    items: [
      {word: "كلا", exact: true},
      {word: "بلى"},
      {word: "نعم", exact: true},
    ],
  },
  {
    group: "أسماء الإشارة",
    items: [
      {word: "ذلك", exact: true},
      {word: "كذلك", exact: true},
      {word: "هذا", exact: true},
    ],
  },
  {
    group: "الوقف قبل الاستفهام",
    items: [
      {word: "هل", mode: "before"},
      {word: "فهل", mode: "before", exact: true},
      {word: "كيف", mode: "before"},
      {word: "فكيف", mode: "before", exact: true},
      {word: "أين", mode: "before"},
      {word: "أنى", mode: "before"},
      {word: "ماذا", mode: "before", exact: true},
    ],
  },
];

export const EDITOR_EDITIONS = new Set(["قطر", "الكويت", "البحرين"]);

export type WaqfMarks = Record<string, string>;

export type ResearchOccurrence = {
  surah: number;
  ayah: number;
  wpos?: number;
  word?: string;
  form?: string;
  waqf?: string;
  marks?: WaqfMarks;
  has_waqf?: boolean;
  context?: string;
  agreement?: "full" | "partial" | string;
  pair?: Array<{word: string; context?: string; marks?: WaqfMarks}>;
};

export type ResearchForm = {word: string; count: number};

export type WordResearchPayload = {
  word: string;
  count: number;
  forms: ResearchForm[];
  occurrences: ResearchOccurrence[];
  active_form: string | null;
};

export type SoloSummary = {id: string; name_ar: string; solo_count: number};
export type SoloDetail = {
  reciter: {id: string; name_ar: string};
  count: number;
  stops: ResearchOccurrence[];
};

export type StatsSurah = {
  surah: number;
  name: string;
  consensus: number;
  divergent: number;
  total: number;
};

export type StatsVerse = {
  surah: number;
  ayah: number;
  divergent: number;
  consensus: number;
  total: number;
};

export type MandatoryPayload = {
  mandatory: ResearchOccurrence[];
  forbidden: ResearchOccurrence[];
  embracing: ResearchOccurrence[];
};

export type Saktah = {
  surah: number;
  ayah: number;
  wpos: number;
  on_word: string;
  next: {surah: number; ayah: number; wpos: number};
  next_word: string;
  category: string;
  cross_verse: boolean;
  reason: string;
  name?: string;
  context?: string;
};

export type IbtidaaItem = {
  surah: number;
  ayah: number;
  stop_word: string;
  resume_word: string;
  back_distance: number;
  count: number;
  stop_marked: boolean;
  context?: string;
  reciters?: string[];
};

export type ClusterMember = {id: string; name_ar: string; qasr?: boolean};
export type ClusterPair = {
  r1?: string;
  r2?: string;
  n1: string;
  n2: string;
  similarity: number;
};
export type ClusterGroup = {
  members: Array<{id: string; name_ar: string}>;
  size: number;
  cohesion: number;
};
export type ClusterPayload = {
  order: ClusterMember[];
  matrix: Record<string, Record<string, number>>;
  range: {min: number; max: number};
  pairs?: ClusterPair[];
  different?: ClusterPair[];
  similar?: ClusterPair[];
  closest?: ClusterPair[];
  clusters: ClusterGroup[];
};

export type AgreeMark = {sym: string; dir: "stop" | "nostop" | "choice"; name: string; glyph: string};
export type AgreeCell = [number, number];
export type AgreementPayload = {
  mushafs: string[];
  mark_config: Record<string, AgreeMark[]>;
  reciters: Array<{id: string; name_ar: string; qasr?: boolean}>;
  agreement: Record<string, Record<string, Record<string, AgreeCell>>>;
  jaiz: Record<string, number>;
};

export type AgreeCasesPayload = {
  verses: Array<{surah: number; ayah: number}>;
  disagreed: number;
  shown?: number;
  capped?: boolean;
};

export type MushafSimTree =
  | {type: "leaf"; id: string; name: string; members?: string[]}
  | {type: "node"; similarity: number; children: MushafSimTree[]; members?: string[]};

export type MushafSimPayload = {
  mushafs: string[];
  standard?: string[];
  order: string[];
  counts?: Record<string, number>;
  pairs: Array<{a: string; b: string; meaning: number; place: number}>;
  tree: MushafSimTree | null;
  marks?: string[];
  mark_consensus?: Array<{
    sym: string;
    glyph: string;
    desc: string;
    positions: number;
    agreement: number;
    counts: Record<string, number>;
  }>;
  profiles?: Array<{
    id: string;
    system: string;
    total: number;
    counts: Record<string, number>;
    special: string[];
  }>;
};

export type MushafDiffPayload = {
  a: string;
  b: string;
  meaning: number;
  differences: number;
  shown: number;
  capped: boolean;
  groups: Array<{a_sym: string; b_sym: string; count: number}>;
  verses: Array<{surah: number; ayah: number; word: string; a_sym: string; b_sym: string}>;
};

export function isLabTab(value: string | null): value is LabTab {
  return LAB_TABS.some((tab) => tab.id === value);
}

export function isLabFamily(value: string | null): value is LabFamily {
  return LAB_FAMILIES.some((family) => family.id === value);
}

export function familyForTab(tab: LabTab): LabFamily {
  return LAB_TABS.find((item) => item.id === tab)?.family || "words";
}

export function firstTabForFamily(family: LabFamily): LabTab {
  return LAB_TABS.find((tab) => tab.family === family)?.id || "word";
}

export function verseHref(surah: number, ayah: number, extra?: {wpos?: number; word?: string}) {
  const params = new URLSearchParams({surah: String(surah), ayah: String(ayah)});
  if (extra?.wpos != null) params.set("wpos", String(extra.wpos));
  if (extra?.word) params.set("hl", extra.word);
  return `/waqf?${params.toString()}`;
}

export function editorHref(edition: string, surah: number, ayah: number) {
  return legacyUrl(`/mushaf-editor?edition=${encodeURIComponent(edition)}&surah=${surah}&ayah=${ayah}`);
}

export function editorEditionsFromMarks(marks?: WaqfMarks) {
  // The editor runs only locally; public pages must not link to it.
  if (process.env.NODE_ENV !== "development") return [];
  return Object.keys(marks || {}).filter((edition) => EDITOR_EDITIONS.has(edition));
}

export function isWarshMushaf(id: string) {
  return id.includes("ورش");
}

export function isHindiMushaf(id: string) {
  return /هندي|indopak/i.test(id);
}

export function mushafFontClass(id: string) {
  if (isWarshMushaf(id)) return "font-athar-warsh";
  if (isHindiMushaf(id)) return "font-athar-hindi";
  return "font-athar-quran";
}

export function mushafGlyph(symbol: string, mushafId: string) {
  if (!symbol || symbol === "∅") return "";
  if (isWarshMushaf(mushafId)) {
    return symbol.split(/[،,]/).map((token) => {
      const part = token.trim();
      if (part === "ص") return "ۖ";
      if (part === "ر") return "۝";
      return waqfMarkGlyph(part) || part;
    }).join("");
  }
  return waqfMarkGlyph(symbol) || symbol;
}

export function agreeVerb(mark: AgreeMark) {
  if (mark.dir === "choice") return "نسبة الوقف";
  return mark.dir === "stop" ? "يقف" : "يصِل";
}

export function agreeDesc(mark: AgreeMark) {
  if (mark.dir === "choice") {
    return "جائز — نسبة وقفه عنده؛ الأعلى يعامله كقلى (يقف)، الأدنى كصلى (يصِل)";
  }
  return `${mark.name} — موافق إذا ${mark.dir === "stop" ? "وقف" : "وصَل (لم يقف)"}`;
}
