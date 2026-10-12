"""Whole-book audit of one edition's waqf column against its own page scans.

    python -m pipeline.cv_waqf book-audit --edition الكويت [--out DIR] [--workers 4] [--pages 1-604]
    python -m pipeline.cv_waqf book-review --edition الكويت [--dir DIR]

Per page (``audit_page``):

1. Detect the signs (``run_page.detect_page``, with the edition's settings —
   including ``snap_boxes``) and compare them with the DB column word by word:
   match / wrong sign / DB mark not seen (``cv_missed``) / sign not in the DB.
   Every disagreement gets a crop and the other prints' marks for that word.
2. Where the page disagrees with the DB, detect again WITHOUT the
   Madinah/Azhar-based adjustments (no seat prior, no reconcile-to-a-seated-word)
   and record which word each sign attaches to then. The adjustments help prints
   that copy Madinah but pull an edition's own seats toward Madinah's (Kuwait
   6:151 «رَبُّكُمۡ»). Measured on 60 Kuwait pages: the two agree on 486/490
   signs, and each is right on some of the rest — so a disagreement is a flag,
   not a verdict.
3. For every DB mark the detector disputes (wrong sign or not seen), look for
   that very sign printed near the word's end (``verify_claims``): a sign-sized
   piece, not touching a letter, not already another word's detected sign,
   whose window reads the DB's sign at >= ``VERIFY_MIN_P``. A printed sign
   confirms one word only — the one whose seat is nearest. Kuwait: 28 of 86
   disputed marks confirmed, all 28 right when checked by eye.

Output in ``--out`` (default ``artifacts/cv-waqf/<edition id>-audit``): ``pages.jsonl``
(resumable), ``crops/``. ``book_review`` turns it into the review page.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import cv2

from pipeline.cv_waqf.config import ARTIFACTS_ROOT, CROP_SIZE, EDITIONS, MUSHAF_WAQF_DATABASE

OTHER_PRINTS = ('الأزهر', 'المدينة الجديد', 'المدينة القديم', 'قطر', 'الكويت', 'البحرين', 'الشمرلي')
VERIFY_MIN_P = 0.95
VERIFY_REACH_X, VERIFY_REACH_UP, VERIFY_REACH_DOWN = 60, 40, 12   # px around the word's seat


def default_out(edition_key: str) -> Path:
    return ARTIFACTS_ROOT / f'{EDITIONS[edition_key].id}-audit'


@contextmanager
def _without_reconcile():
    """detect_page with the reconcile-to-a-seated-word step switched off."""
    from pipeline.cv_waqf import run_page as rp
    orig = rp._nearest_word
    rp._nearest_word = lambda *a, **k: None
    try:
        yield
    finally:
        rp._nearest_word = orig


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _crop(img, box, out_dir: Path, name: str, colour=(0, 0, 230)) -> str:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    X0, Y0 = max(0, cx - 170), max(0, cy - 55)
    tile = img[Y0:cy + 85, X0:cx + 170].copy()
    cv2.rectangle(tile, (x0 - X0 - 3, y0 - Y0 - 3), (x1 - X0 + 3, y1 - Y0 + 3), colour, 2)
    cv2.imwrite(str(out_dir / 'crops' / name), tile, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return name


class _OtherPrints:
    """Marks of the other prints for a layout word. Layout word positions skip a
    leading ۞; mushaf_waqf.token_index counts it."""

    def __init__(self, script_db: str):
        self.conn = sqlite3.connect(f'file:{MUSHAF_WAQF_DATABASE}?mode=ro', uri=True)
        cols = {r[1] for r in self.conn.execute('PRAGMA table_info(waqf)')}
        self.cols = [c for c in OTHER_PRINTS if c in cols]
        script = sqlite3.connect(f'file:{script_db}?mode=ro', uri=True)
        self.hizb = {tuple(map(int, k.split(':')[:2])) for (k,) in script.execute(
            "SELECT word_key FROM words WHERE word_key LIKE '%:1' AND trim(text)='۞'")}

    def __call__(self, word_key: str, exclude: str) -> dict:
        s, a, w = map(int, word_key.split(':'))
        w += (s, a) in self.hizb
        cols = [c for c in self.cols if c != exclude]
        row = self.conn.execute(
            'SELECT ' + ','.join(f'"{c}"' for c in cols)
            + ' FROM waqf WHERE "السورة"=? AND "الآية"=? AND token_index=?', (s, a, w)).fetchone()
        return {c: v for c, v in zip(cols, row or []) if v}


def pick_confirming(scored, ink_share: float, min_p: float = VERIFY_MIN_P):
    """Among (component, p) pairs, the piece that confirms the sign: of those at
    >= min_p, the HIGHEST one with a sign's ink — a vowel beside the sign also
    reads as the sign (same rule as snap.py). None when nothing confirms."""
    hits = [(c, p) for c, p in scored if p >= min_p]
    if not hits:
        return None
    biggest = max(c[4] for c, _ in hits)
    return min(((c, p) for c, p in hits if c[4] >= ink_share * biggest),
               key=lambda cp: cp[0][1] + cp[0][3] / 2)


def one_sign_one_word(found: dict) -> dict:
    """{word_key: {'box', 'seat_d', ...}}: a printed sign confirms only the word
    whose seat is nearest to it; the others lose it (Kuwait 43:80)."""
    owner = {}
    for key, r in found.items():
        b = tuple(r['box'])
        if b not in owner or r['seat_d'] < found[owner[b]]['seat_d']:
            owner[b] = key
    return {key: r for key, r in found.items() if owner[tuple(r['box'])] == key}


def verify_claims(prep, words, wanted: dict, other_boxes, clf):
    """{word_key: DB sign} → {word_key: {'found', 'p', 'box', 'seat_d'}}."""
    from pipeline.cv_waqf import geometry
    from pipeline.cv_waqf.candidates import crop_candidate
    from pipeline.cv_waqf.line_gaps import _ccs_in_roi
    from pipeline.cv_waqf.snap import INK_SHARE, MIN_AREA, SIGN_MAX_SIDE, TEXT_GAP, _gap, _window

    out, found = {}, {}
    for key, sym in wanted.items():
        w = words.get(key)
        if w is None or sym not in clf.classes:
            continue
        sx, sy = geometry.mark_seat_centre(w.x0, w.y0, w.y1)
        roi = _ccs_in_roi(prep.binary, int(sx - VERIFY_REACH_X) - TEXT_GAP, int(sy - VERIFY_REACH_UP) - TEXT_GAP,
                          int(sx + VERIFY_REACH_X) + TEXT_GAP, int(sy + VERIFY_REACH_DOWN) + TEXT_GAP)
        strokes = [c for c in roi if max(c[2], c[3]) > SIGN_MAX_SIDE]
        comps = [c for c in roi if c[4] >= MIN_AREA and max(c[2], c[3]) <= SIGN_MAX_SIDE
                 and not any(_gap(c, t) <= TEXT_GAP for t in strokes)
                 and not any(b[0] <= c[0] + c[2] / 2 <= b[2] and b[1] <= c[1] + c[3] / 2 <= b[3]
                             for b in other_boxes)]
        best, top_p = None, 0.0
        if comps:
            li = clf.classes.index(sym)
            probs = clf.predict_many_probs([crop_candidate(prep.gray, _window(c[0] + c[2] / 2, c[1] + c[3] / 2, c[4]),
                                                           size=CROP_SIZE) for c in comps])
            scored = [(c, float(p[li])) for c, (_l, _c, p) in zip(comps, probs)]
            top_p = max(p for _, p in scored)
            best = pick_confirming(scored, INK_SHARE)
        out[key] = {'found': False, 'p': round(best[1] if best else top_p, 3)}
        if best:
            c = best[0]
            found[key] = {'box': [c[0], c[1], c[0] + c[2], c[1] + c[3]],
                          'seat_d': round(((c[0] + c[2] / 2 - sx) ** 2 + (c[1] + c[3] / 2 - sy) ** 2) ** 0.5, 1)}
    kept = one_sign_one_word(found)
    for key, r in found.items():
        out[key].update(r, found=key in kept)
        if key not in kept:
            out[key]['taken_by'] = next(k for k, v in kept.items() if v['box'] == r['box'])
    return out


def audit_page(edition_key: str, page: int, out_dir: str) -> dict:
    from pipeline.cv_waqf import run_page as rp
    from pipeline.cv_waqf.classify import GlyphClassifier
    from pipeline.cv_waqf.config import resolve_edition_model
    from pipeline.cv_waqf.layout_geo import estimate_layout_words
    from pipeline.cv_waqf.marks import edition_marks_for_ayahs
    from pipeline.cv_waqf.preprocess import load_bgr, preprocess_page

    out = Path(out_dir)
    spec = EDITIONS[edition_key]
    others = _OtherPrints(spec.script_db)
    rec = {'page': page, 'items': [], 'counts': {}}
    try:
        res = rp.detect_page(edition_key, page)
        rec['model'] = Path(res['model']).name if res.get('model') else None
        img = load_bgr(res['image'])
        prep = preprocess_page(img.copy(), spec, page=page)
        words = estimate_layout_words(spec, page, prep)
        by_id = {w.word_id: w for w in words}
        keys = sorted({(w.surah, w.ayah) for w in words if w.surah})
        db = {k: v for k, v in edition_marks_for_ayahs(edition_key, keys, spec.script_db).items()
              if k[2] in by_id and v != 'ركوع'}
        cv = {(m['surah'], m['ayah'], m['word_id']): m for m in res['marks'] if m.get('surah')}
        counts = dict(match=0, wrong=0, missing=0, extra=0)
        for k, m in cv.items():
            if k not in db:
                kind = 'not_in_db'
            elif db[k] != m['symbol']:
                kind = 'symbol_differs'
            else:
                counts['match'] += 1
                continue
            counts['wrong' if kind == 'symbol_differs' else 'extra'] += 1
            name = f"p{page:03d}_{m['word_key'].replace(':', '-')}.jpg"
            rec['items'].append({
                'kind': kind, 'word_key': m['word_key'], 'text': m['text'], 'cv': m['symbol'],
                'conf': m['confidence'], 'db': db.get(k), 'box': m['box'],
                'others': others(m['word_key'], spec.mushaf_version), 'crop': _crop(img, m['box'], out, name),
            })
        for k, sym in db.items():
            if k in cv:
                continue
            counts['missing'] += 1
            w = by_id[k[2]]
            name = f"p{page:03d}_{w.word_key.replace(':', '-')}_miss.jpg"
            rec['items'].append({
                'kind': 'cv_missed', 'word_key': w.word_key, 'text': w.text, 'cv': None, 'conf': None,
                'db': sym, 'others': others(w.word_key, spec.mushaf_version),
                'crop': _crop(img, (w.x0, w.y0, w.x1, w.y1), out, name),
            })
        rec['counts'] = counts

        # 2. owners without the Madinah/Azhar adjustments
        if any(i['kind'] in ('not_in_db', 'symbol_differs') for i in rec['items']):
            with _without_reconcile():
                raw = rp.detect_page(edition_key, page, azhar_prior=False)
            for i in rec['items']:
                if 'box' not in i:
                    continue
                b = max(raw['marks'], key=lambda b: _iou(i['box'], b['box']), default=None)
                if b is not None and _iou(i['box'], b['box']) > 0.5:
                    i['raw'] = {'raw_key': b['word_key'], 'raw_text': b['text']}

        # 3. is the DB's disputed sign printed near the word's end?
        wanted = {i['word_key']: i['db'] for i in rec['items']
                  if i['kind'] in ('symbol_differs', 'cv_missed') and i['db']}
        if wanted:
            clf = GlyphClassifier(model_path=resolve_edition_model(edition_key)[0])
            layout = {w.word_key: w for w in words}
            other_boxes = [m['box'] for m in res['marks'] if m['word_key'] not in wanted]
            checks = verify_claims(prep, layout, wanted, other_boxes, clf)
            for i in rec['items']:
                v = checks.get(i['word_key'])
                if v is None or i['kind'] not in ('symbol_differs', 'cv_missed'):
                    continue
                if v['found']:
                    name = f"p{page:03d}_{i['word_key'].replace(':', '-')}_confirm.jpg"
                    v['crop'] = _crop(img, v['box'], out, name, colour=(0, 160, 0))
                i['verify'] = v
    except Exception as exc:  # noqa: BLE001 — one bad page must not stop the book
        rec['error'] = repr(exc)
    return rec


def _work(args):
    return audit_page(*args)


def run(edition_key: str, out_dir: Path, pages: list[int], workers: int = 4) -> Path:
    import multiprocessing as mp

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'crops').mkdir(exist_ok=True)
    log = out_dir / 'pages.jsonl'
    done = {json.loads(line)['page'] for line in log.open()} if log.exists() else set()
    todo = [p for p in pages if p not in done]
    jobs = [(edition_key, p, str(out_dir)) for p in todo]
    ctx = mp.get_context('spawn')          # cv2/onnx are not fork-safe on macOS
    with log.open('a') as fh, ctx.Pool(max(1, workers)) as pool:
        for n, rec in enumerate(pool.imap_unordered(_work, jobs), 1):
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
            fh.flush()
            if n % 25 == 0 or n == len(jobs):
                print(f'{n}/{len(jobs)} pages', flush=True)
    return log


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog='python -m pipeline.cv_waqf book-audit')
    p.add_argument('--edition', required=True, choices=list(EDITIONS))
    p.add_argument('--out', type=Path)
    p.add_argument('--pages', default=None, help='e.g. 1-604 (default: the whole book)')
    p.add_argument('--workers', type=int, default=4)
    args = p.parse_args(argv)
    spec = EDITIONS[args.edition]
    if args.pages:
        a, _, b = args.pages.partition('-')
        pages = list(range(int(a), int(b or a) + 1))
    else:
        pages = list(range(spec.min_page, spec.max_page + 1))
    log = run(args.edition, args.out or default_out(args.edition), pages, args.workers)
    print(f'wrote {log}')
    return 0
