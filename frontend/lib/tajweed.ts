import { getJson } from "@/lib/api";

export type TajweedPart = {
  text: string;
  rule: string;
};

export type TajweedSegment = {
  parts: TajweedPart[];
};

type TajweedPayload = {html: string};

const tajweedCache = new Map<string, Promise<TajweedSegment[]>>();
const HAMZA = /[ءأؤإئ]/;
const SAFE_RULE = /^[a-z_]+$/;

function normalizeRule(value: string) {
  const rule = value.trim().split(/\s+/)[0] || "";
  return SAFE_RULE.test(rule) ? rule : "";
}

function reclassifyMunfasil(parts: TajweedPart[]) {
  const lastMadda = parts.map((part) => part.rule).lastIndexOf("madda_obligatory");
  if (lastMadda < 0) return parts;
  const marked = parts[lastMadda]?.text || "";
  const after = parts.slice(lastMadda + 1).map((part) => part.text).join("");
  if (HAMZA.test(marked) || HAMZA.test(after)) return parts;
  return parts.map((part) => part.rule === "madda_obligatory"
    ? {...part, rule: "madda_munfasil"}
    : part);
}

export function parseTajweedHtml(html: string) {
  if (typeof DOMParser === "undefined") return [];
  const document = new DOMParser().parseFromString(`<div>${html}</div>`, "text/html");
  const root = document.body.firstElementChild;
  if (!root) return [];
  const tokens: Array<TajweedPart & {boundary?: boolean}> = [];

  root.childNodes.forEach((node) => {
    const element = node.nodeType === Node.ELEMENT_NODE ? node as HTMLElement : null;
    const rule = element ? normalizeRule(element.getAttribute("class") || "") : "";
    if (rule === "end") return;
    const text = node.textContent || "";
    text.split(" ").forEach((part, index, parts) => {
      if (part) tokens.push({text: part, rule, boundary: index < parts.length - 1});
      else if (index < parts.length - 1) tokens.push({text: "", rule, boundary: true});
    });
  });

  const segments: TajweedSegment[] = [];
  let parts: TajweedPart[] = [];
  const flush = () => {
    if (parts.map((part) => part.text).join("").trim()) {
      segments.push({parts: reclassifyMunfasil(parts)});
    }
    parts = [];
  };
  tokens.forEach((token) => {
    if (token.text) parts.push({text: token.text, rule: token.rule});
    if (token.boundary) flush();
  });
  flush();
  return segments;
}

export function getTajweedSegments(surah: number, ayah: number) {
  const key = `${surah}:${ayah}`;
  let request = tajweedCache.get(key);
  if (!request) {
    request = getJson<TajweedPayload>(`/backend-api/tajweed/${surah}/${ayah}`)
      .then((payload) => parseTajweedHtml(payload.html || ""))
      .catch(() => []);
    tajweedCache.set(key, request);
  }
  return request;
}

function isCombiningMark(character: string) {
  const codepoint = character.codePointAt(0) || 0;
  return (codepoint >= 0x064b && codepoint <= 0x065f) || codepoint === 0x0670 ||
    (codepoint >= 0x06d6 && codepoint <= 0x06ed) ||
    (codepoint >= 0x0610 && codepoint <= 0x061a) ||
    (codepoint >= 0x0653 && codepoint <= 0x0658) ||
    codepoint === 0x06e5 || codepoint === 0x06e6;
}

function alignmentSkeleton(character: string) {
  const codepoint = character.codePointAt(0) || 0;
  if ([0x0622, 0x0623, 0x0625, 0x0627, 0x0671, 0x0621, 0x0624, 0x0626].includes(codepoint)) return "A";
  if (codepoint === 0x0649 || codepoint === 0x064a) return "Y";
  if (codepoint === 0x0629) return "H";
  return character;
}

function alignDisplayToSource(source: string[], display: string[]) {
  const scores = Array.from({length: source.length + 1}, () => new Int32Array(display.length + 1));
  for (let sourceIndex = 1; sourceIndex <= source.length; sourceIndex += 1) {
    scores[sourceIndex][0] = scores[sourceIndex - 1][0] - 1;
  }
  for (let displayIndex = 1; displayIndex <= display.length; displayIndex += 1) {
    scores[0][displayIndex] = scores[0][displayIndex - 1] - 1;
  }
  for (let sourceIndex = 1; sourceIndex <= source.length; sourceIndex += 1) {
    for (let displayIndex = 1; displayIndex <= display.length; displayIndex += 1) {
      const match = alignmentSkeleton(source[sourceIndex - 1]) === alignmentSkeleton(display[displayIndex - 1]) ? 2 : -1;
      scores[sourceIndex][displayIndex] = Math.max(
        scores[sourceIndex - 1][displayIndex - 1] + match,
        scores[sourceIndex - 1][displayIndex] - 1,
        scores[sourceIndex][displayIndex - 1] - 1,
      );
    }
  }
  const alignment = new Array(display.length).fill(-1);
  let sourceIndex = source.length;
  let displayIndex = display.length;
  while (sourceIndex > 0 && displayIndex > 0) {
    const match = alignmentSkeleton(source[sourceIndex - 1]) === alignmentSkeleton(display[displayIndex - 1]) ? 2 : -1;
    if (scores[sourceIndex][displayIndex] === scores[sourceIndex - 1][displayIndex - 1] + match) {
      alignment[displayIndex - 1] = sourceIndex - 1;
      sourceIndex -= 1;
      displayIndex -= 1;
    } else if (scores[sourceIndex][displayIndex] === scores[sourceIndex - 1][displayIndex] - 1) {
      sourceIndex -= 1;
    } else {
      displayIndex -= 1;
    }
  }
  return alignment;
}

export function tajweedPartsForDisplay(displayWord: string, segment?: TajweedSegment) {
  if (!segment?.parts.some((part) => part.rule)) return [{text: displayWord, rule: ""}];
  const sourceCharacters: string[] = [];
  const sourceRules: string[] = [];
  segment.parts.forEach((part) => {
    [...part.text].forEach((character) => {
      sourceCharacters.push(character);
      sourceRules.push(part.rule);
    });
  });
  const displayCharacters = [...displayWord];
  const rules = new Array(displayCharacters.length).fill("");
  const alignment = alignDisplayToSource(sourceCharacters, displayCharacters);
  displayCharacters.forEach((_, index) => {
    const sourceIndex = alignment[index];
    if (sourceIndex >= 0) rules[index] = sourceRules[sourceIndex] || "";
  });

  let index = 0;
  while (index < displayCharacters.length) {
    const start = index;
    index += 1;
    while (index < displayCharacters.length && isCombiningMark(displayCharacters[index])) index += 1;
    const rule = rules.slice(start, index).find(Boolean) || "";
    for (let cluster = start; cluster < index; cluster += 1) rules[cluster] = rule;
  }

  const output: TajweedPart[] = [];
  displayCharacters.forEach((character, characterIndex) => {
    const rule = rules[characterIndex];
    const previous = output.at(-1);
    if (previous && previous.rule === rule) previous.text += character;
    else output.push({text: character, rule});
  });
  return output;
}
