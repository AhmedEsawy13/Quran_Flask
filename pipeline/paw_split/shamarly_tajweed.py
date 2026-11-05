"""Tajweed colours for the marks (harakat) and letters of the Shamarly vector print.

Rule data: quran-ws/quran-tajweed (CC BY 4.0; reviewed, 164 rules, per-ayah spans measured against its pinned
Uthmani Hafs edition). Both the spans and that edition text are downloaded to artifacts/quran-ws-tajweed/ on first
use (not redistributed from this repository).

A span covers letters and the marks drawn on them. Marks: each mark code point inside
a span is carried over to the letter of our text it sits on (the two texts are aligned letter by letter; they
differ only by waqf signs and verse-number tokens), and the small outlines of the print that sit within that
letter's x-interval, above or below the writing line like the mark, take the rule's colour. Letter intervals come
from Kraken's letter positions (see shamarly_kraken_spans.py). A coloured outline is a whole outline: a dot of
the letter or a stacked mark can take the colour with it.

Letters (ayah_letters/pick_letters): which letters of a span take its colour depends on the rule (the first
letter for qalqalah and the shadda letters, the madd letter for madd, every letter for iqlab, ikhfa and idgham). The
reader clips the word's body to the letter's x-interval; the interval edges are midpoints between Kraken's letters,
so a colour can bleed a little where strokes overlap.

The colours are the reader's existing tajweed classes (frontend app/globals.css `.tajweed-rule.<class>`).
"""
from __future__ import annotations

import collections
import difflib
import json
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / 'artifacts' / 'quran-ws-tajweed'
RAW = 'https://raw.githubusercontent.com/quran-ws/quran-tajweed/main'
FILES = {'annotations.json': 'packages/annotations/uthmani-hafs.json', 'edition.json': 'editions/uthmani-hafs.json'}

# quran-ws rule (the id without its trailing .N) -> (the reader's tajweed class, priority: higher wins when
# several rules cover the same mark). Izhar, tafkheem/tarqeeq, leen and ghunnah-of-ikhfa are not coloured here.
RULE_CLASS: dict[str, tuple[str, int]] = {
    'qalqalah-sughra': ('qalaqah', 90), 'qalqalah-kubra': ('qalaqah', 90), 'qalqalah-mutatarrifa': ('qalaqah', 90),
    'iqlab-noon': ('iqlab', 85), 'iqlab-tanween': ('iqlab', 85),
    'ikhfa-haqiqi-noon': ('ikhafa', 80), 'ikhfa-haqiqi-tanween': ('ikhafa', 80),
    'ikhfa-shafawi-meem': ('ikhafa_shafawi', 80), 'mutajanisain-ikhfa-shafawi': ('ikhafa_shafawi', 80),
    'idgham-bi-ghunnah-noon': ('idgham_ghunnah', 75), 'idgham-bi-ghunnah-tanween': ('idgham_ghunnah', 75),
    'idgham-naqis-noon': ('idgham_ghunnah', 75), 'idgham-naqis-tanween': ('idgham_ghunnah', 75),
    'idgham-bila-ghunnah-noon': ('idgham_wo_ghunnah', 74), 'idgham-bila-ghunnah-tanween': ('idgham_wo_ghunnah', 74),
    'idgham-kamil-noon': ('idgham_wo_ghunnah', 70), 'idgham-kamil-tanween': ('idgham_wo_ghunnah', 70),
    'idgham-shafawi-meem': ('idgham_shafawi', 75),
    'mutamathilain-idgham-kamil': ('idgham_mutajanisayn', 72), 'mutajanisain-idgham-naqis': ('idgham_mutajanisayn', 72),
    'noon-mushaddadah': ('ghunnah', 60), 'meem-mushaddadah': ('ghunnah', 60),
    'madd-lazim-kalimi-muthaqqal': ('madda_necessary', 55), 'madd-lazim-kalimi-mukhaffaf': ('madda_necessary', 55),
    'madd-lazim-harfi': ('madda_necessary', 55),
    'madd-muttasil': ('madda_obligatory', 50), 'madd-munfasil': ('madda_munfasil', 50),
    'madd-tabee-kalimi': ('madda_normal', 30), 'madd-iwad': ('madda_normal', 30), 'madd-badal': ('madda_normal', 30),
    'madd-silah-sughra': ('madda_normal', 30),
}


def fetch() -> tuple[dict, list]:
    """(annotations, {ayah key: edition text}) from the local cache, downloaded on first use."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        if not (CACHE / name).is_file():
            with urllib.request.urlopen(f'{RAW}/{path}', timeout=60) as r:
                (CACHE / name).write_bytes(r.read())
    return json.load(open(CACHE / 'annotations.json')), json.load(open(CACHE / 'edition.json'))['ayahs']


def _is_mark(c: str) -> bool:
    return unicodedata.category(c).startswith('M')


# kasra, kasratan, subscript alef, hamza below, vowel sign dot below, wavy hamza below, small low seen / meem
BELOW = {0x0650, 0x064D, 0x0656, 0x0655, 0x065C, 0x065F, 0x06E3, 0x06ED}


def _side(c: str) -> str:
    """Which side of the writing line a mark sits on."""
    return 'below' if ord(c) in BELOW else 'above'


class Tajweed:
    def __init__(self, norm_letter, is_letter):
        self.ann, self.edition = fetch()
        self.rule_ids = self.ann['ruleIds']
        self.norm = norm_letter
        self.is_letter = is_letter

    # Which letters of a span take its colour. Spans also hold context letters: a madd span has the letter
    # before the madd letter, an idgham span the trigger letter of the next word.
    MADD_LETTERS = set('اويىآ')

    @staticmethod
    def pick_letters(hukum: str, raws: list[str]) -> list[int]:
        """Indices (into the span's letters, raw characters) that are coloured."""
        n = len(raws)
        if hukum.startswith('qalqalah') or hukum in ('noon-mushaddadah', 'meem-mushaddadah'):
            return [0] if n else []
        if hukum in ('madd-muttasil',):
            return []                                           # the madd sign (a mark) is coloured, not a letter
        if hukum in ('madd-lazim-kalimi-muthaqqal', 'madd-lazim-kalimi-mukhaffaf'):
            return [i for i, c in enumerate(raws) if c == 'آ'][:1]
        if hukum == 'madd-lazim-harfi':
            return [n - 1] if n else []
        if hukum.startswith('madd-'):                           # tabee, iwad, badal, silah, munfasil: the madd letter
            idx = [i for i, c in enumerate(raws) if c in Tajweed.MADD_LETTERS]
            return idx[-1:] if hukum != 'madd-munfasil' else idx[:1]
        return list(range(n))                                   # iqlab, ikhfa, idgham: every letter of the span

    def ayah_letters(self, ayah_key: str, our_words: list[tuple[int, str]]) -> dict:
        """{(word_index, letter index in word): (class, priority)} for the letters one ayah's rules colour."""
        spans = self.ann['spans'].get(ayah_key) or []
        text = list(self.edition.get(ayah_key) or '')
        if not spans or not text:
            return {}
        their = [(self.norm(ch), pos) for pos, ch in enumerate(text) if self.is_letter(ch)]
        letter_at = {pos: i for i, (_, pos) in enumerate(their)}
        ours = []
        for wi, t in our_words:
            for j, ch in enumerate([c for c in t if self.is_letter(c)]):
                ours.append((wi, j, self.norm(ch)))
        sm = difflib.SequenceMatcher(None, [b for b, _ in their], [b for _, _, b in ours], autojunk=False)
        to_ours = {}
        for a0, b0, size in sm.get_matching_blocks():
            for t_ in range(size):
                to_ours[a0 + t_] = ours[b0 + t_][:2]
        out: dict = {}
        for s, e, ri in spans:
            hukum = self.rule_ids[ri].rsplit('.', 1)[0]
            cls = RULE_CLASS.get(hukum)
            if not cls:
                continue
            idxs = [letter_at[p] for p in range(s, e) if p in letter_at]
            raws = [text[their[i][1]] for i in idxs]
            for k in self.pick_letters(hukum, raws):
                key = to_ours.get(idxs[k])
                if key is not None and (key not in out or cls[1] > out[key][1]):
                    out[key] = cls
        return out

    def ayah_marks(self, ayah_key: str, our_words: list[tuple[int, str]]) -> dict:
        """{(word_index, letter index in word): {side: (class, priority)}} for the marks of one ayah.

        ``our_words``: [(word_index, text)] of the whole ayah in our script."""
        spans = self.ann['spans'].get(ayah_key) or []
        text = list(self.edition.get(ayah_key) or '')
        if not spans or not text:
            return {}
        # letters of their text with the position of each; marks hang on the letter before them
        their, letter_of = [], {}
        for pos, ch in enumerate(text):
            if self.is_letter(ch):
                their.append((self.norm(ch), pos))
            letter_of[pos] = len(their) - 1
        ours = []
        for wi, t in our_words:
            for j, ch in enumerate([c for c in t if self.is_letter(c)]):
                ours.append((wi, j, self.norm(ch)))
        sm = difflib.SequenceMatcher(None, [b for b, _ in their], [b for _, _, b in ours], autojunk=False)
        to_ours = {}
        for a0, b0, size in sm.get_matching_blocks():
            for t_ in range(size):
                to_ours[a0 + t_] = ours[b0 + t_][:2]
        out: dict = collections.defaultdict(dict)
        for s, e, ri in spans:
            hukum = self.rule_ids[ri].rsplit('.', 1)[0]
            cls = RULE_CLASS.get(hukum)
            if not cls:
                continue
            for pos in range(s, e):
                ch = text[pos]
                if not _is_mark(ch) or letter_of.get(pos, -1) < 0:
                    continue
                key = to_ours.get(letter_of[pos])
                if key is None:
                    continue
                side = _side(ch)
                cur = out[key].get(side)
                if cur is None or cls[1] > cur[1]:
                    out[key][side] = cls
        return out


def letter_bounds(png, cx0: float, words: list[tuple[int, str]], K, offset_px: float = 0.0) -> dict:
    """{(word_index, letter index): (x0, x1)} in PDF points for the letters of one line.

    ``words``: [(word_index, text)] in reading order; ``K``: shamarly_kraken_partition. Kraken reads the line crop
    (``png``, whose left edge is ``cx0`` pt), its letters are aligned to the known ones, unplaced letters are spread
    between their placed neighbours, and a letter's interval runs to the midpoint with each neighbour."""
    ws = [(wi, K.norm_letters(t)) for wi, t in words]
    ws = [(wi, ls) for wi, ls in ws if ls]
    if not ws:
        return {}
    pred, xs = K.kraken_read(png)
    predl = [(K.MAP.get(K.base(c), K.base(c)), i) for i, c in enumerate(pred) if K.is_letter(c)]
    flat, ids = [], []
    for k in reversed(range(len(ws))):                        # image order, left to right
        wi, ls = ws[k]
        for j in reversed(range(len(ls))):
            flat.append(ls[j])
            ids.append((wi, j))
    sm = difflib.SequenceMatcher(None, [c for c, _ in predl], flat, autojunk=False)
    pos = {}
    for a0, b0, size in sm.get_matching_blocks():
        for t in range(size):
            if predl[a0 + t][1] < len(xs):
                pos[b0 + t] = xs[predl[a0 + t][1]]
    if len(pos) < 2:
        return {}
    idx = sorted(pos)
    cen = [pos[idx[0]] + (i - idx[0]) * 0.0 for i in range(len(flat))]
    # linear in index between placed letters, flat beyond the ends at the average letter pitch
    pitch = (pos[idx[-1]] - pos[idx[0]]) / max(1, idx[-1] - idx[0])
    for i in range(len(flat)):
        if i < idx[0]:
            cen[i] = pos[idx[0]] - (idx[0] - i) * pitch
        elif i > idx[-1]:
            cen[i] = pos[idx[-1]] + (i - idx[-1]) * pitch
        else:
            lo = max(t for t in idx if t <= i)
            hi = min(t for t in idx if t >= i)
            cen[i] = pos[lo] if lo == hi else pos[lo] + (pos[hi] - pos[lo]) * (i - lo) / (hi - lo)
    edges = [cen[0] - (cen[1] - cen[0]) / 2] + [(cen[i] + cen[i + 1]) / 2 for i in range(len(cen) - 1)] \
        + [cen[-1] + (cen[-1] - cen[-2]) / 2]
    return {ids[i]: (cx0 + (edges[i] - offset_px) / K.Z, cx0 + (edges[i + 1] - offset_px) / K.Z) for i in range(len(flat))}
