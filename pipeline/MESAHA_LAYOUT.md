# مصحف المساحة الأميرية ١٣٤٢هـ

Layout Studio ID: `mesaha`

Sources:

- [Internet Archive 2017 item](https://archive.org/details/mushafElMesaha46796794669_201703)
- [Quranpedia-linked 2025 Archive item](https://archive.org/details/mushafElMesahaFP.pdf)

The scan has 850 leaves; the Quran project uses printed/PDF pages 2–827
(826 pages). Archive leaf numbers are zero-based, so printed page N uses
Archive leaf N−1.

## Rebuild the automatic seed

Download both DjVu XML derivatives, install development requirements, then run:

```bash
python3 pipeline/import_mesaha_layout.py \
  --ocr-xml archive-2017=data/mesaha-ocr/mushafElMesaha_djvu.xml \
  --ocr-xml quranpedia-2025=data/mesaha-ocr/mushafElMesaha.pdf_djvu.xml \
  --force
```

The importer refuses to overwrite an existing project without `--force`.
`--force` is destructive: it removes all Layout Studio edits, progress, and
undo history.

v3 improvements (over the first seed):

- Canonical stream ordered by `surah, ayah, word_index` (fixes interleaved
  `word_index` chunks that scrambled surah-boundary pages).
- Multi-source **fusion** of OCR matches (not winner-take-all).
- Page word-count prior (~70–130) to repair extreme cuts.
- Softer line anchors + ratio-based confidence badges.
- Surah-banner OCR lines filtered / used only as positional bias.

The importer never generates Quran text. It aligns noisy OCR observations to
the ordered canonical words in `data/quran_script.db`, emits every canonical
word exactly once, fuses OCR candidates across sources, then constructs one
continuous layout. It writes per-page confidence and source provenance to
`layout_import_confidence`. The committed report is
`data/mushaf-mesaha-import-report.json`.

## Review order

1. Review low-confidence pages first (red badge).
2. Then review medium-confidence pages (amber badge).
3. Sample and approve high-confidence pages.
4. A page is authoritative only after the reviewer checks
   **مطابِق للمطبوع**. Import confidence is not scholarly approval.

Opening pages 2 and 3 are explicit eight-slot layouts. Other pages default to
12 physical slots. Surah name, surah information, and basmallah each consume
one slot; سورة التوبة has no basmallah.

## Supabase

Run `pipeline/supabase_expand_layout_page_range.sql` once before saving pages
above 604 to Supabase. It replaces the old 604-page checks with the universal
positive-page constraint.

Do not add this edition to the Waqf Editor until its layout pages have passed
review. Waqf extraction and publication are a separate phase.
