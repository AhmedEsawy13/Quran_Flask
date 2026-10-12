// Print the pause signs drawn on QVP pages, per word, as JSON on stdout.
// Uses the app's own decoder (frontend/lib/qvp-lite.ts). Run through
// pipeline/audit_qvp_waqf.py:
//   node --experimental-strip-types scripts/qvp_extract_marks.ts <pagesDir>
import { readFileSync } from "node:fs";
import { decodeGeometry } from "../frontend/lib/qvp-lite.ts";

// qvp-format `Mark` ids for the pause signs (Family::Waqf, plus Saktah).
const MARK: Record<number, string> = { 21: "ج", 22: "ق", 23: "ص", 24: "م", 25: "ع", 26: "س" };

const pagesDir = process.argv[2];
const out: Record<string, string[]> = {};
for (let page = 1; page <= 604; page++) {
  const geo = decodeGeometry(readFileSync(`${pagesDir}/${String(page).padStart(3, "0")}.qvp`));
  for (const word of geo.words) {
    const marks: string[] = [];
    for (let i = word.firstPath; i < word.firstPath + word.nPaths; i++) {
      const path = geo.paths[i];
      if (path.family !== 4 && path.mark !== 26) continue;
      const mark = MARK[path.mark];
      if (!mark) throw new Error(`page ${page}: unknown pause mark ${path.mark}`);
      if (!marks.includes(mark)) marks.push(mark);
    }
    if (marks.length) out[`${word.surah}:${word.ayah}:${word.word}`] = marks.sort();
  }
}
process.stdout.write(JSON.stringify(out));
