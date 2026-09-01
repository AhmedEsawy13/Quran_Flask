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
  same_surah?: boolean;
};

export type MemorizationContextSegment = {
  segment_id: number;
  topic_id: string | number;
  title: string;
  from: string;
  to: string;
  verse_keys: string[];
};

export type MemorizationContextMap = {
  segments: MemorizationContextSegment[];
  attribution?: string;
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

export type TawjihPayload = {
  surah: number;
  ayah: number;
  count: number;
  source: {
    name: string;
    title: string;
    author: string;
    url: string;
  };
  entries: Array<{
    wpos: number;
    stop_word: string;
    quote: string;
    note: string;
    grade: string | null;
    url: string;
    created_at: string | null;
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

export type PracticeVerdict = "excellent" | "good" | "ok" | "unmarked" | "caution" | "error";

export type PracticeVerse = {
  ayah: number;
  words: string[];
};

export type PracticePassage = {
  surah: number;
  verses: PracticeVerse[];
};

export type PracticeGradedStop = {
  ayah: number;
  wpos: number;
  word: string;
  verdict: PracticeVerdict;
  label: string;
  mark: string;
  has_mark: boolean;
};

export type PracticeMarkRef = {
  ayah: number;
  wpos: number;
  word: string;
  mark: string;
};

export type PracticeGrade = {
  surah: number;
  from_ayah: number;
  to_ayah: number;
  mushaf: string;
  score: number;
  summary: {good: number; notes: number; errors: number};
  counts: Record<PracticeVerdict, number>;
  stops: PracticeGradedStop[];
  broken_lazim: PracticeMarkRef[];
  ideal: PracticeMarkRef[];
};

export type EerabPayload = {
  content: string;
};

export type SearchHit = {
  verse_key: string;
  surah_number: number;
  ayah_number: number;
  text: string;
  highlight?: boolean;
};

export type SearchPayload = {
  query: string;
  total_results: number;
  results: SearchHit[];
  source: string;
};

type ApiErrorBody = {
  error?: string;
};

async function readJsonBody<T>(response: Response): Promise<T | ApiErrorBody> {
  try {
    return (await response.json()) as T | ApiErrorBody;
  } catch {
    throw new Error("تعذّر قراءة استجابة الخادم.");
  }
}

function errorMessage(body: ApiErrorBody | unknown, status: number) {
  const message =
    body && typeof body === "object" && "error" in body
      ? (body as ApiErrorBody).error
      : undefined;
  return message || `تعذّر الاتصال بالخادم (${status}).`;
}

export async function getJson<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    signal,
    headers: { Accept: "application/json" },
  });
  const body = await readJsonBody<T>(response);
  if (!response.ok) throw new Error(errorMessage(body, response.status));
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
  const body = await readJsonBody<T>(response);
  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    throw new Error(errorMessage(body, response.status));
  }
  return body as T;
}

export async function postJson<T>(
  path: string,
  payload: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    signal,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const body = await readJsonBody<T>(response);
  if (!response.ok) throw new Error(errorMessage(body, response.status));
  return body as T;
}
