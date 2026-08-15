import type { VerseTiming } from "@/lib/api";
import { toArabicDigits } from "@/lib/mushaf";

export type MemorizationStepKind = "phrase" | "phrase-link" | "verse" | "ayah-link";

export type MemorizationStep = {
  key: string;
  kind: MemorizationStepKind;
  start: number;
  end: number;
  startAyah: number;
  endAyah: number;
  label: string;
  repetition: number;
  repetitionTotal: number;
};

export const PHRASE_START_PAD = 0.12;
export const UNIT_END_PAD = 0.28;
export const CONTIGUOUS_SLACK = 0.12;

export function stepSeekTime(step: {kind: string; start: number}) {
  return step.kind === "phrase" || step.kind === "phrase-link"
    ? Math.max(0, step.start - PHRASE_START_PAD)
    : step.start;
}

export function isContiguousAdvance(
  current: {end: number},
  next?: {start: number} | null,
) {
  return Boolean(next && next.start >= current.end - CONTIGUOUS_SLACK);
}

export function stepStopTime(
  step: {kind: string; end: number},
  next?: {start: number} | null,
) {
  if (isContiguousAdvance(step, next) && next) {
    return Math.max(step.end, next.start);
  }
  return step.end + UNIT_END_PAD;
}

export type MemorizationScheduleOptions = {
  fromAyah: number;
  toAyah: number;
  unitRepetitions: number;
  linkRepetitions: number;
  cumulative: boolean;
  splitAtPauses: boolean;
};

function addRepeatedSteps(
  steps: MemorizationStep[],
  base: Omit<MemorizationStep, "key" | "repetition" | "repetitionTotal">,
  count: number,
) {
  const total = Math.max(1, count);
  for (let repetition = 1; repetition <= total; repetition += 1) {
    steps.push({
      ...base,
      key: `${base.kind}:${base.startAyah}:${base.endAyah}:${base.start}:${base.end}:${repetition}`,
      repetition,
      repetitionTotal: total,
    });
  }
}

export function buildMemorizationSchedule(
  verses: VerseTiming[],
  options: MemorizationScheduleOptions,
) {
  const selected = verses.filter(
    (verse) => verse.ayah >= options.fromAyah && verse.ayah <= options.toAyah,
  );
  const steps: MemorizationStep[] = [];
  const firstVerse = selected[0];

  selected.forEach((verse, verseIndex) => {
    const phrases = verse.phrases.filter((phrase) => phrase.end > phrase.start);
    const usePhrases = options.splitAtPauses && phrases.length > 1;

    if (usePhrases) {
      phrases.forEach((phrase, phraseIndex) => {
        addRepeatedSteps(steps, {
          kind: "phrase",
          start: phrase.start,
          end: phrase.end,
          startAyah: verse.ayah,
          endAyah: verse.ayah,
          label: `الآية ${toArabicDigits(verse.ayah)} · المقطع ${toArabicDigits(phraseIndex + 1)} من ${toArabicDigits(phrases.length)}`,
        }, options.unitRepetitions);

        if (options.cumulative && phraseIndex > 0) {
          addRepeatedSteps(steps, {
            kind: "phrase-link",
            start: phrases[0].start,
            end: phrase.end,
            startAyah: verse.ayah,
            endAyah: verse.ayah,
            label: `ربط مقاطع الآية ${toArabicDigits(verse.ayah)}`,
          }, 1);
        }
      });

      addRepeatedSteps(steps, {
        kind: "verse",
        start: verse.start,
        end: verse.end,
        startAyah: verse.ayah,
        endAyah: verse.ayah,
        label: `الآية ${toArabicDigits(verse.ayah)} كاملة`,
      }, 1);
    } else {
      addRepeatedSteps(steps, {
        kind: "verse",
        start: verse.start,
        end: verse.end,
        startAyah: verse.ayah,
        endAyah: verse.ayah,
        label: `الآية ${toArabicDigits(verse.ayah)}`,
      }, options.unitRepetitions);
    }

    if (options.cumulative && verseIndex > 0 && firstVerse) {
      addRepeatedSteps(steps, {
        kind: "ayah-link",
        start: firstVerse.start,
        end: verse.end,
        startAyah: firstVerse.ayah,
        endAyah: verse.ayah,
        label: `ربط الآيات ${toArabicDigits(firstVerse.ayah)}–${toArabicDigits(verse.ayah)}`,
      }, options.linkRepetitions);
    }
  });

  return steps;
}

export function firstStepForAyah(steps: MemorizationStep[], ayah: number) {
  const exactUnit = steps.findIndex(
    (step) => step.startAyah === ayah && (step.kind === "phrase" || step.kind === "verse"),
  );
  if (exactUnit >= 0) return exactUnit;
  return Math.max(0, steps.findIndex((step) => ayah >= step.startAyah && ayah <= step.endAyah));
}
