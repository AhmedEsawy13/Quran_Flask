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
