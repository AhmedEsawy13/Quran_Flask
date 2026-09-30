# Mushaf font rendering audit — 2026-07-18

## Scope

The تثبيت renderer was exercised in the real browser against every page of both bundled Madinah editions:

- Old Madinah 1405 (`qpc_v1`)
- Digital Khatt / new Madinah (`digital_khatt`)
- Desktop single page: 1280 × 720
- Mobile single page: 390 × 844
- Desktop two-page spread: 1280 × 720

This produced 3,624 page-render checks and 52,773 justified-line measurements. Centered surah headings, basmalas, and deliberately centered ayah lines were excluded from full-justification checks.

## Acceptance thresholds

| Check | Passing threshold |
|---|---:|
| Horizontal compression | `scaleX >= 0.95` (no more than 5%) |
| Residual word spacing | `<= 4px` |
| Difference between line and text edge | `<= 1.1px` |
| Single-page fallback expansion | Old Madinah `<= 18%`; Digital Khatt `<= 15%` |
| Two-page fallback expansion | `<= 20%` |
| Facing-page fitted-size difference | `<= 15%` |

## Final result

| Scenario | Old Madinah | Digital Khatt |
|---|---:|---:|
| Desktop single page | 604 / 604 pass | 604 / 604 pass |
| Mobile single page | 604 / 604 pass | 604 / 604 pass |
| Desktop two-page spread | 604 / 604 pass | 604 / 604 pass |

There are no remaining pages outside the compression, word-spacing, or edge-alignment thresholds in the audited configurations.

## Problems found and corrections

### Desktop single page

- Old Madinah initially had 17 rare short-line edge outliers. The worst was page 51 at 31.15px short after the old 6% expansion ceiling. The strongest available font alternates were already active, so the bounded fallback was raised to 18%. Targeted final measurements are within 0.58px.
- Digital Khatt initially had three short-line edge outliers. The worst was page 511 at 11.91px. Adding the font's `cv03` elongation combinations and using a 15% fallback ceiling brought the targeted final measurements within 0.78px.

### Mobile single page

- Old Madinah pages 570 and 577 reached the former 11px font floor, producing 5.08% and 5.49% compression. The configurable floor now permits the fitter to reach its calculated safe size; both pages finish at approximately 3.86% compression.
- Digital Khatt page 507 reached the former 10.5px floor and compressed one line by 8.94%. It now fits at 9.99px with 4.27% compression, 1.36px maximum word spacing, and a 0.56px edge difference.

### Desktop two-page spread

- A single shared font size made the easier facing page inherit the difficult page's much smaller size. This created four Old Madinah and seven Digital Khatt edge outliers; the worst was Digital Khatt page 69 at 46.08px short.
- Fully independent fitting removed the geometry error but produced a visually excessive 27% font-size difference between facing pages.
- The final compromise fits each page independently, caps the facing-page size difference at 15%, and permits at most 20% fallback expansion in spread mode. All former spread outliers now pass; the corrected page 69 line uses 18.47% expansion and finishes within 0.90px of the edge.

## Final rendering strategy

1. Fit each page against its longest natural line with a 5% compression budget.
2. Cache by source, layout, page/spread, and rendered page dimensions.
3. Select the closest supported Arabic elongation feature combination per line.
4. Cap residual word spacing based on the rendered font size.
5. Use bounded whole-line expansion only when the font alternates and spacing cap cannot fill the line.
6. In spreads, fit both pages independently but keep their font-size ratio within 1.15.

## Regression focus

The following pages are useful as a compact high-risk corpus in addition to the exhaustive run:

- Old Madinah: 29, 51, 88, 279, 353, 358, 378, 507, 536, 570, 577
- Digital Khatt: 29, 41, 60, 69, 168, 279, 349, 353, 358, 445, 507, 511, 557

Future font or layout changes should rerun the same three viewport/layout scenarios and retain the thresholds above.

## Automated enforcement

The measurements are now reproducible with `scripts/audit_mushaf_fonts.py`:

```bash
python3 scripts/audit_mushaf_fonts.py --mode risk
python3 scripts/audit_mushaf_fonts.py --mode full
```

`.github/workflows/mushaf-font-audit.yml` runs the high-risk corpus when font,
layout, or renderer files change in a pull request. A weekly schedule and the
manual workflow run the exhaustive 604-page mode. Both modes upload JSON and
Markdown reports and fail when any threshold in this document is exceeded.
