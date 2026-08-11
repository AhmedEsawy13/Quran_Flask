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

export function toArabicDigits(value: number | string) {
  return String(value).replace(/[0-9]/g, (digit) => "٠١٢٣٤٥٦٧٨٩"[Number(digit)]);
}

export function juzLabelForPage(pageNumber: number) {
  let juz = 1;
  for (let index = 0; index < JUZ_START_PAGES.length; index += 1) {
    if (pageNumber >= JUZ_START_PAGES[index]) juz = index + 1;
    else break;
  }
  return `الجزء ${JUZ_NAMES[juz - 1]}`;
}
