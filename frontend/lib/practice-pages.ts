import {getJson, type MushafPage, type MushafWord} from "@/lib/api";
import {MUSHAF_EDITIONS, type MushafEditionId} from "@/lib/mushaf";

export const PRACTICE_PAGE_LIMIT = 8;

const PRACTICE_EDITIONS: Partial<Record<string, MushafEditionId>> = {
  "المدينة الجديد": "digital_khatt",
  "المدينة القديم": "qpc_v1",
  "الأزهر": "azhar_amiri",
  "الشمرلي": "shamarly",
};

export function practiceEditionId(mushaf: string): MushafEditionId {
  return PRACTICE_EDITIONS[mushaf] || "digital_khatt";
}

export function practiceUsesApproximateLayout(mushaf: string) {
  return !(mushaf in PRACTICE_EDITIONS);
}

export function hasArabicLetters(text: string) {
  return /[ء-ي]/.test(text || "");
}

export function maxAyahOnPage(page: MushafPage, surah: number) {
  let maximum = 0;
  page.lines.forEach((line) => {
    line.words.forEach((word) => {
      if (Number(word.surah) === surah && Number(word.ayah) > maximum) {
        maximum = Number(word.ayah);
      }
    });
  });
  return maximum;
}

export function assignPracticePositions(pages: MushafPage[]) {
  const positions = new WeakMap<MushafWord, number>();
  const next = new Map<string, number>();
  pages.forEach((page) => {
    page.lines.forEach((line) => {
      line.words.forEach((word) => {
        if (word.surah == null || word.ayah == null || !hasArabicLetters(word.text || "")) return;
        const key = `${word.surah}:${word.ayah}`;
        const wpos = next.get(key) || 0;
        positions.set(word, wpos);
        next.set(key, wpos + 1);
      });
    });
  });
  return positions;
}

export async function loadPracticePageRange(
  mushaf: string,
  surah: number,
  fromAyah: number,
  toAyah: number,
  signal?: AbortSignal,
) {
  const editionId = practiceEditionId(mushaf);
  const edition = MUSHAF_EDITIONS[editionId];
  const query = `?mushaf_version=${encodeURIComponent(mushaf)}`;
  const first = await getJson<MushafPage>(
    `/backend-api/${edition.apiBase}/page-by-ayah/${surah}/${fromAyah}${query}`,
    signal,
  );
  if (!first?.lines?.length) {
    throw new Error(`تعذّر تحميل صفحة مصحف ${mushaf}.`);
  }
  const pages = [first];
  while (pages.length < PRACTICE_PAGE_LIMIT && maxAyahOnPage(pages[pages.length - 1], surah) < toAyah) {
    const nextNumber = Number(pages[pages.length - 1].page_number) + 1;
    if (!nextNumber) break;
    const next = await getJson<MushafPage>(
      `/backend-api/${edition.apiBase}/page/${nextNumber}${query}`,
      signal,
    );
    if (!next?.lines?.length) break;
    pages.push(next);
  }
  if (maxAyahOnPage(pages[pages.length - 1], surah) < toAyah) {
    throw new Error(`تعذّر عرض المقطع كاملًا على صفحات مصحف ${mushaf}.`);
  }
  return pages;
}
