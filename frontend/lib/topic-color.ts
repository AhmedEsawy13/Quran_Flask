const TOPIC_PALETTE = [
  "#2f6f9f", "#8a5a2b", "#39745a", "#80558c", "#a14e55", "#5f6f2f",
  "#386f7a", "#7a5b9e", "#9a6728", "#4365a8", "#8b5368", "#4f7550",
] as const;

export function topicColor(topicId?: string | number | null, title = "") {
  const source = String(topicId ?? title ?? "");
  let hash = 2166136261;
  for (let i = 0; i < source.length; i += 1) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return TOPIC_PALETTE[Math.abs(hash) % TOPIC_PALETTE.length];
}

export function topicPathParts(title?: string) {
  return String(title || "")
    .split(":")
    .map((part) => part.trim())
    .filter(Boolean);
}

export type TopicWash = {
  color: string;
  segmentId: number;
};
