"""Word cuts a reviewer set by hand, and how they are applied to the review data.

A cut is the boundary between two neighbouring words of one printed row. It is identified by the keys of the
word on its right (earlier in reading order) and the word on its left, so it survives a rebuild of the proposals:
``build_review`` hands the same cuts to the cutter, which then puts them exactly there.
"""
from __future__ import annotations

import copy

MIN_WORD_PX = 6        # a word box can not be dragged narrower than this


def cut_key(page: int, right_key: str, left_key: str) -> str:
    return f'{page}:{right_key}|{left_key}'


def pinned_cuts(cuts: dict) -> dict[tuple[str, str], float]:
    """``{(right word key, left word key): x}`` for ``layout_geo.estimate_layout_words(fixed_cuts=...)``."""
    out: dict[tuple[str, str], float] = {}
    for key, value in cuts.items():
        pair = key.partition(':')[2].partition('|')
        if pair[1]:
            out[(pair[0], pair[2])] = float(value['x'])
    return out


def neighbours(words: list[dict], right_key: str, left_key: str) -> tuple[dict, dict] | None:
    """The two words if the left one directly follows the right one in the same row, else ``None``."""
    for a, b in zip(words, words[1:]):
        if a['key'] == right_key and b['key'] == left_key and a['line'] == b['line']:
            return a, b
    return None


def valid_x(right: dict, left: dict, x: float) -> bool:
    """A cut must leave both words at least ``MIN_WORD_PX`` wide."""
    return left['box'][0] + MIN_WORD_PX <= x <= right['box'][2] - MIN_WORD_PX


def apply_cuts(pages: list[dict], cuts: dict) -> list[dict]:
    """A copy of ``pages`` with every cut moved to where the reviewer put it.

    The boxes of the two words (and of their proposals) change, the stop seat of the word on the right follows its
    left edge, and both words stop being doubtful: a person looked at the cut.
    """
    if not cuts:
        return pages
    out = copy.deepcopy(pages)
    for page in out:
        mine = {k: v for k, v in cuts.items() if k.startswith(f"{page['page']}:")}
        if not mine:
            continue
        for key, value in mine.items():
            right_key, _, left_key = key.partition(':')[2].partition('|')
            pair = neighbours(page['words'], right_key, left_key)
            if pair is None:
                continue
            x = float(value['x'])
            for group in (page['words'], page.get('proposals') or []):
                for w in group:
                    if w['key'] not in (right_key, left_key):
                        continue
                    if w['key'] == right_key:
                        w['seat'] = [w['seat'][0] + (x - w['box'][0]), w['seat'][1]]
                        w['box'][0] = round(x)
                        w['dl'] = 0.0                  # the cut on this word's left is the one that moved
                    else:
                        w['box'][2] = round(x)
                        w['dr'] = 0.0
                    w['dw'] = 0.0                      # a person looked at the word's box
                    w['doubt'] = round(1 - (1 - w.get('dr', 0.0)) * (1 - w.get('dl', 0.0)), 2)
                    if not w['doubt']:
                        w['why'] = ''
                    w['cut_fixed'] = True
    return out


def use_hand_cuts(data_dir) -> int:
    """Make every layout estimate in this process put the reviewer's cuts where they set them.

    The review pipeline (detection, tiers, the review data) calls this first so all of it sees the same boxes.
    Returns how many cuts were loaded.
    """
    import json
    from pathlib import Path

    from pipeline.cv_waqf import layout_geo

    try:
        cuts = json.loads((Path(data_dir) / 'cuts.json').read_text(encoding='utf-8'))
    except FileNotFoundError:
        cuts = {}
    layout_geo.FIXED_CUTS = pinned_cuts(cuts)
    return len(layout_geo.FIXED_CUTS)
