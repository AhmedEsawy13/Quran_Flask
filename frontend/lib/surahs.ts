import {getJson, type Surah} from "@/lib/api";

let catalog: Promise<Surah[]> | null = null;

/** The surah list, fetched once per page load and shared by every caller. */
export function loadSurahs() {
  catalog ??= getJson<Surah[]>("/backend-api/surahs").catch((reason: unknown) => {
    catalog = null;
    throw reason;
  });
  return catalog;
}
