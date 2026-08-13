import {toArabicDigits} from "@/lib/mushaf";
import type {PracticeGradedStop, PracticeVerdict} from "@/lib/api";

export const MAX_PRACTICE_SPAN = 20;
export const DEFAULT_MUSHAF = "المدينة الجديد";
const PREFERRED_MUSHAF = ["المدينة الجديد", "المدينة القديم"] as const;

export const PRACTICE_VERDICTS: Record<PracticeVerdict, {cls: string; name: string; tip: string}> = {
  excellent: {cls: "ex", name: "علامة قوية", tip: "وقف لازم في المصحف"},
  good: {cls: "good", name: "علامة جائزة", tip: "قلى / ج / معانقة / رأس آية"},
  ok: {cls: "ok", name: "الوصل أولى", tip: "صلى أو سكتة — الوقف مسموح"},
  unmarked: {cls: "un", name: "بلا علامة", tip: "لا علامة وقف في هذا المصحف"},
  caution: {cls: "caut", name: "موضع فيه نظر", tip: "راجع هذا الوقف على المطبوع"},
  error: {cls: "err", name: "لا وقف", tip: "علامة «لا» — لا يُوقف عليه"},
};

export function orderMushafVersions(versions: string[]) {
  const preferred = PREFERRED_MUSHAF.filter((name) => versions.includes(name));
  const rest = versions.filter((name) => !PREFERRED_MUSHAF.includes(name as typeof PREFERRED_MUSHAF[number]));
  return [...preferred, ...rest];
}

export function stopKey(ayah: number, wpos: number) {
  return `${ayah}:${wpos}`;
}

export function parseStopKey(key: string) {
  const [ayah, wpos] = key.split(":").map(Number);
  return {ayah, wpos};
}

export function practiceScoreTitle(score: number, errors: number) {
  if (errors === 0 && score >= 95) return "ممتاز — وقوفك يوافق علامات المصحف";
  if (score >= 85) return "أحسنت — راجع المواضع بلا علامة";
  if (score >= 65) return "جيّد — قارن وقوفك بعلامات المصحف";
  return "يحتاج مراجعة — توقّف عند «لا» أو فاتك لازم";
}

export function practiceScoreTone(score: number) {
  if (score >= 85) return "hi";
  if (score >= 65) return "mid";
  return "lo";
}

export function markCaption(stop: Pick<PracticeGradedStop, "has_mark" | "mark" | "label">) {
  if (stop.has_mark && stop.mark) {
    return `علامة المصحف: ${stop.mark}` + (stop.label ? ` — ${stop.label}` : "");
  }
  return stop.label || "بلا علامة في هذا المصحف";
}

export function stopCountLabel(count: number) {
  if (count === 0) return "لم تُعلّم أي وقف بعد";
  if (count === 1) return "علّمتَ موضع وقف واحد";
  if (count === 2) return "علّمتَ موضعي وقف";
  return `علّمتَ ${toArabicDigits(count)} مواضع وقف`;
}
