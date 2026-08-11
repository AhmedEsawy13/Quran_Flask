export type Surah = {
  number: number;
  name: string;
  englishName: string;
};

export type WordMeaning = {
  word: string;
  meaning: string;
  word_no: number;
};

export type Ayah = {
  ayah_number: number;
  surah_number: number;
  verse_key: string;
  text: string;
  clean_text?: string;
  transliteration?: { t?: string };
  word_meanings_ordered?: WordMeaning[];
  word_meanings_source?: {
    provider?: string;
    attribution?: string;
  };
};

export type Reciter = {
  id: string;
  name_ar: string;
  name_en: string;
};

export type VerseTiming = {
  ayah: number;
  verse_key: string;
  start: number;
  end: number;
  text: string;
  phrases: Array<{ start: number; end: number }>;
  words: Array<[number, number, number]>;
};

export type MemorizationAudio = {
  surah_number: number;
  reciter: string;
  reciter_id: string;
  reciter_name_ar: string;
  audio_url: string;
  audio_offset_ms: number;
  verses: VerseTiming[];
};

export type MemorizationContext = {
  found: boolean;
  surah: number;
  ayah: number;
  topic_id?: string | number;
  title?: string;
  label?: string;
  attribution?: string;
  from?: { surah: number; ayah: number };
  to?: { surah: number; ayah: number };
  run_length?: number;
  score?: number;
};

export type WaqfStop = {
  wpos: number;
  time: number;
};

export type WaqfPhrase = {
  first_wpos: number;
  last_wpos: number;
  start: number;
  end: number;
};

export type WaqfReciterDetail = {
  name_ar: string;
  stops: WaqfStop[];
  repeats: Array<{from_wpos: number; to_wpos: number}>;
  phrases: WaqfPhrase[];
  duration: number;
  audio_url: string | null;
  verse_start: number;
  qasr_munfasil: boolean;
  solo_stops_detail: Array<{
    wpos: number;
    time: number;
    word: string;
    mushaf_matches: Array<{mushaf: string; symbol: string}>;
  }>;
};

export type WaqfPayload = {
  surah: number;
  ayah: number;
  verse_key: string;
  text: string;
  words: string[];
  reciters_total: number;
  full_duration: number | null;
  ref_times: number[] | null;
  ref_full: number | null;
  ref_reciter: string | null;
  reciters: Array<{id: string; name_ar: string}>;
  per_reciter: Record<string, WaqfReciterDetail>;
  union_stops: Array<{
    wpos: number;
    reciters: string[];
    count: number;
    solo: boolean;
    avg_duration: number;
  }>;
  mushafs: Array<{
    id: string;
    name: string;
    marks: Array<{wpos: number; symbol: string}>;
  }>;
};

export type ClassicalWaqfPayload = {
  surah: number;
  ayah: number;
  count: number;
  sources: Record<string, {
    name: string;
    title: string;
    author: string;
    edition: string;
    via: string;
  }>;
  entries: Array<{
    source: string;
    wpos: number;
    stop_word: string;
    quote: string;
    grade: string;
    grade_raw: string;
    note: string;
    reported_from: string | null;
  }>;
};

export type TafseerCollection = Record<string, { text: string }>;

export type MutashabihatMatch = {
  surah: number;
  ayah: number;
  verse_key: string;
  words: string[];
  longest_run: number;
  shared: number;
  coverage: number;
  near_duplicate: boolean;
  opcodes: Array<[string, number, number, number, number]>;
};

export type MutashabihatPayload = {
  surah: number;
  ayah: number;
  verse_key: string;
  count: number;
  matches: MutashabihatMatch[];
};

export type AsbabEntry = {
  source: string;
  text: string;
  attribution: string;
};

export type AsbabPayload = {
  verse_key: string;
  available: boolean;
  entries: AsbabEntry[];
  message?: string;
};

export type MushafWord = {
  ayah: number;
  surah: number;
  text: string;
  word_index?: number;
  word_key?: string;
  suppress_render?: boolean;
  waqf_symbols?: string | Array<{symbols: string; version: string}>;
};

export type MushafLine = {
  line_number: number;
  line_type: "ayah" | "surah_name" | "surah_info" | "basmallah" | string;
  is_centered?: boolean;
  surah_number?: number | string;
  display_text?: string;
  contains_focus_ayah?: boolean;
  words: MushafWord[];
};

export type MushafPage = {
  source?: string;
  page_number: number;
  font_name: string;
  layout_name?: string;
  lines_per_page?: number;
  glyph_mapping_mode?: "shemrly-page-local" | "legacy-word-position" | string;
  focus_surah?: number;
  focus_ayah?: number;
  anchor_surah_number?: number;
  anchor_ayah_number?: number;
  lines: MushafLine[];
};

type ApiErrorBody = {
  error?: string;
};

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    signal,
    headers: { Accept: "application/json" },
  });

  let body: T | ApiErrorBody | null = null;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    throw new Error("تعذّر قراءة استجابة الخادم.");
  }

  if (!response.ok) {
    const message =
      body && typeof body === "object" && "error" in body
        ? body.error
        : undefined;
    throw new Error(message || `تعذّر الاتصال بالخادم (${response.status}).`);
  }

  return body as T;
}

export async function getJsonAccepting<T>(
  path: string,
  acceptedStatuses: number[],
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    signal,
    headers: { Accept: "application/json" },
  });

  let body: T | ApiErrorBody | null = null;
  try {
    body = (await response.json()) as T | ApiErrorBody;
  } catch {
    throw new Error("تعذّر قراءة استجابة الخادم.");
  }

  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    const message =
      body && typeof body === "object" && "error" in body
        ? body.error
        : undefined;
    throw new Error(message || `تعذّر الاتصال بالخادم (${response.status}).`);
  }

  return body as T;
}
