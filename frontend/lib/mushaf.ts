export const MUSHAF_EDITIONS = {
  digital_khatt: {
    id: "digital_khatt",
    label: "المدينة ١٤٤١هـ",
    shortLabel: "رسم المدينة الحديث",
    description: "أوضح رسم رقمي للقراءة اليومية، وفق صفحة المدينة ذات ١٥ سطرًا.",
    waqfSource: "المدينة الجديد",
    apiBase: "digital-khatt",
    fontFamily: '"Digital Khatt", "Uthmanic Hafs", serif',
    font: {
      family: "Digital Khatt",
      url: "/fonts/digitalkhatt.woff2",
    },
  },
  qpc_v2: {
    id: "qpc_v2",
    label: "المدينة ١٤٢١هـ",
    shortLabel: "الرسم الرقمي الثاني",
    description: "نسخة رقمية أقدم قليلًا من رسم المدينة، مع توزيع الصفحة المطبوع.",
    waqfSource: "المدينة الجديد",
    apiBase: "qpc-v2",
    fontFamily: '"Digital Khatt", "Uthmanic Hafs", serif',
    font: {
      family: "Digital Khatt",
      url: "/fonts/digitalkhatt.woff2",
    },
  },
  qpc_v1: {
    id: "qpc_v1",
    label: "المدينة ١٤٠٥هـ",
    shortLabel: "طبعة المدينة القديمة",
    description: "رسم طبعة المدينة القديمة لمن اعتاد شكلها وتوزيع كلماتها.",
    waqfSource: "المدينة القديم",
    apiBase: "qpc-v1",
    fontFamily: '"Old Madina", "Uthmanic Hafs", serif',
    font: {
      family: "Old Madina",
      url: "/fonts/oldmadina.woff2",
    },
  },
  azhar_amiri: {
    id: "azhar_amiri",
    label: "الأزهر — خط أميري",
    shortLabel: "رسم الأزهر بخط أميري",
    description: "صفحة الأزهر ذات ١٥ سطرًا، بخط أميري وعلامات وقف الأزهر الواضحة.",
    waqfSource: "الأزهر",
    apiBase: "azhar",
    fontFamily: '"Amiri Quran", "Uthmanic Hafs", serif',
    font: {
      family: "Amiri Quran",
      url: "/fonts/amiri-quran.woff2",
    },
  },
  shamarly: {
    id: "shamarly",
    label: "الشمرلي — صفحات مختارة",
    shortLabel: "رسم الشمرلي المطبوع",
    description: "خط الصفحة الأصلي من مصحف الشمرلي؛ يتوفر حاليًا للصفحات التي اكتمل استخراج خطها فقط.",
    waqfSource: "الشمرلي",
    apiBase: "shamarly",
    fontFamily: '"Uthmanic Hafs", serif',
    dynamicPageFont: true,
    font: {
      family: "Uthmanic Hafs",
      url: "/fonts/uthmanic-hafs.woff2",
    },
  },
} as const;

export type MushafEditionId = keyof typeof MUSHAF_EDITIONS;
export type ReaderView = "verse" | "page";

export function isMushafEdition(value: string | null): value is MushafEditionId {
  return value !== null && value in MUSHAF_EDITIONS;
}

export function isReaderView(value: string | null): value is ReaderView {
  return value === "verse" || value === "page";
}

const JUZ_START_PAGES = [
  1, 22, 42, 62, 82, 102, 121, 142, 162, 182, 201, 222, 242, 262, 282,
  302, 322, 342, 362, 382, 402, 422, 442, 462, 482, 502, 522, 542, 562, 582,
];

const JUZ_NAMES = [
  "الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع",
  "الثامن", "التاسع", "العاشر", "الحادي عشر", "الثاني عشر", "الثالث عشر",
  "الرابع عشر", "الخامس عشر", "السادس عشر", "السابع عشر", "الثامن عشر",
  "التاسع عشر", "العشرون", "الحادي والعشرون", "الثاني والعشرون",
  "الثالث والعشرون", "الرابع والعشرون", "الخامس والعشرون", "السادس والعشرون",
  "السابع والعشرون", "الثامن والعشرون", "التاسع والعشرون", "الثلاثون",
];

const JUZ_START_AYAHS = [
  [1, 1], [2, 142], [2, 253], [3, 92], [4, 24], [4, 148], [5, 82], [6, 111],
  [7, 88], [8, 41], [9, 93], [11, 6], [12, 53], [15, 1], [17, 1], [18, 75],
  [21, 1], [23, 1], [25, 21], [27, 56], [29, 46], [33, 31], [36, 28], [39, 32],
  [41, 47], [46, 1], [51, 31], [58, 1], [67, 1], [78, 1],
] as const;

// The original Flask Mushaf uses one outline per Surah from surah_names.woff2.
// Glyph rank follows Surah order, not Unicode codepoint order.
const SURAH_HEADER_CODEPOINTS = [
  0xfc45, 0xfc46, 0xfc47, 0xfc4a, 0xfc4b, 0xfc4e, 0xfc4f, 0xfc51, 0xfc52, 0xfc53,
  0xfc55, 0xfc56, 0xfc58, 0xfc5a, 0xfc5b, 0xfc5c, 0xfc5d, 0xfc5e, 0xfc61, 0xfc62,
  0xfc64, 0xfb51, 0xfb52, 0xfb54, 0xfb55, 0xfb57, 0xfb58, 0xfb5a, 0xfb5b, 0xfb5d,
  0xfb5e, 0xfb60, 0xfb61, 0xfb63, 0xfb64, 0xfb66, 0xfb67, 0xfb69, 0xfb6a, 0xfb6c,
  0xfb6d, 0xfb6f, 0xfb70, 0xfb72, 0xfb73, 0xfb75, 0xfb76, 0xfb78, 0xfb79, 0xfb7b,
  0xfb7c, 0xfb7e, 0xfb7f, 0xfb81, 0xfb82, 0xfb84, 0xfb85, 0xfb87, 0xfb88, 0xfb8a,
  0xfb8b, 0xfb8d, 0xfb8e, 0xfb90, 0xfb91, 0xfb93, 0xfb94, 0xfb96, 0xfb97, 0xfb99,
  0xfb9a, 0xfb9c, 0xfb9d, 0xfb9f, 0xfba0, 0xfba2, 0xfba3, 0xfba5, 0xfba6, 0xfba8,
  0xfba9, 0xfbab, 0xfbac, 0xfbae, 0xfbaf, 0xfbb1, 0xfbb2, 0xfbb4, 0xfbb5, 0xfbb7,
  0xfbb8, 0xfbba, 0xfbbb, 0xfbbd, 0xfbbe, 0xfbc0, 0xfbc1, 0xfbd3, 0xfbd4, 0xfbd6,
  0xfbd7, 0xfbd9, 0xfbda, 0xfbdc, 0xfbdd, 0xfbdf, 0xfbe0, 0xfbe2, 0xfbe3, 0xfbe5,
  0xfbe6, 0xfbe8, 0xfbe9, 0xfbeb,
] as const;

export function toArabicDigits(value: number | string) {
  return String(value).replace(/[0-9]/g, (digit) => "٠١٢٣٤٥٦٧٨٩"[Number(digit)]);
}

export function juzNumberForPage(pageNumber: number) {
  let juz = 1;
  for (let index = 0; index < JUZ_START_PAGES.length; index += 1) {
    if (pageNumber >= JUZ_START_PAGES[index]) juz = index + 1;
    else break;
  }
  return juz;
}

export function juzNumberFromAyah(surahNumber: number, ayahNumber: number) {
  let juz = 1;
  for (let index = 0; index < JUZ_START_AYAHS.length; index += 1) {
    const [surah, ayah] = JUZ_START_AYAHS[index];
    if (surahNumber > surah || (surahNumber === surah && ayahNumber >= ayah)) juz = index + 1;
    else break;
  }
  return juz;
}

export function juzLabel(juzNumber: number) {
  const safeNumber = Math.min(30, Math.max(1, Math.trunc(juzNumber) || 1));
  return `الجزء ${JUZ_NAMES[safeNumber - 1]}`;
}

export function juzLabelForPage(pageNumber: number) {
  return juzLabel(juzNumberForPage(pageNumber));
}

export function juzHeaderGlyph(juzNumber: number) {
  return juzNumber >= 1 && juzNumber <= 30
    ? String.fromCodePoint(0xe000 + juzNumber)
    : "";
}

export function surahHeaderGlyph(surahNumber: number) {
  const codepoint = SURAH_HEADER_CODEPOINTS[surahNumber - 1];
  return codepoint ? String.fromCodePoint(codepoint) : "";
}
