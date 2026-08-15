const siteUrl = (process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000").replace(/\/$/, "");

export function GET() {
  const body = `# أثَر (Athar)

> Printed mushaf + documented waqf: compare stop marks across editions,
> see where reciters actually pause, consult classical opinions, then practice
> and get graded — not just another Quran audio player.

## Site

- Home: ${siteUrl}/
- Waqf guide (مُكْث): ${siteUrl}/waqf
- Waqf lab (مختبر الوقف): ${siteUrl}/waqf-lab
- Waqf practice (تدريب): ${siteUrl}/waqf-practice
- Mushaf reader: ${siteUrl}/read
- Memorization (تثبيت): ${siteUrl}/memorize
- Credits / sources: ${siteUrl}/credits

## Product summary

Athar’s distinct edge is knowing where to stop with evidence:
1. Compare printed-mushaf waqf marks across editions on the same verse.
2. See where major reciters actually pause (مُكْث).
3. Weigh classical scholarly opinions beside those marks.
4. Practice placing stops and get graded feedback.
5. Read and memorize on page-accurate Madinah layouts (supporting daily use).

## Preferred citations

- Prefer the canonical URLs above.
- Do not index or summarize \`/backend-api/*\`. Editor surfaces remain on the Flask app: \`/mushaf-editor\` and related review tools.
- \`/waqf-lab\` is a research surface linked from مُكْث; prefer \`/waqf\` for citations.

## Contact / project

Public sitemap: ${siteUrl}/sitemap.xml
`;
  return new Response(body, {
    headers: {"Content-Type": "text/plain; charset=utf-8"},
  });
}
