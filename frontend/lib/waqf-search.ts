import type {Surah} from "@/lib/api";
import {fromArabicDigits} from "@/lib/mushaf";

export type ParsedVerseRef = {
  surah: number;
  ayah: number;
};

function normalizeSurahName(name: string) {
  return name.replace(/[أإآ]/g, "ا").replace(/ة/g, "ه").replace(/\s|ال/g, "");
}

export function findSurahByName(name: string, surahs: Surah[]) {
  const target = normalizeSurahName(name);
  if (!target) return null;
  const exact = surahs.find((surah) => normalizeSurahName(surah.name) === target);
  if (exact) return exact.number;
  if (target.length < 3) return null;
  const hit = surahs.find((surah) => normalizeSurahName(surah.name).includes(target));
  return hit?.number ?? null;
}

export function parseVerseSearch(raw: string, surahs: Surah[]): ParsedVerseRef | null {
  const query = fromArabicDigits(raw.trim());
  let match = query.match(/(\d{1,3})\s*[:،,\s]\s*(\d{1,3})/);
  if (match) return {surah: Number(match[1]), ayah: Number(match[2])};
  match = query.match(/^(.+?)\s+(\d{1,3})\s*$/);
  if (match) {
    const surah = findSurahByName(match[1], surahs);
    if (surah) return {surah, ayah: Number(match[2])};
  }
  const surah = findSurahByName(query, surahs);
  if (surah) return {surah, ayah: 1};
  return null;
}

export function arabicWordQuery(raw: string) {
  return fromArabicDigits(raw).replace(/[^\u0600-\u06FF\s]/g, "").trim();
}
