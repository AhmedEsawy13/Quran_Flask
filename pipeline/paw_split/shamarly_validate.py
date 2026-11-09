"""Structural checks of the built Shamarly pages: every invariant a bug has broken so far, in one run.

    python3 pipeline/paw_split/shamarly_validate.py [--svg-dir DIR] [--qvp-dir DIR] [pages ...]
    QVP_CONVERT=/path/to/qvp-convert  (optional: also decodes every .qvp with `qvp-convert info`)

Exit status 1 when any page fails. The checks (and what broke without them):

  xml            the SVG parses
  empty_path     no path without ink                                (empty mark paths made two identical d="" -> glyph instances
                                                                      -> an undecodable .qvp)
  duplicate_d    no two paths with the same d string                (same cause: qvp-convert turns repeats into instances)
  thin_path      no path under 0.1 pt wide or high                   (a zero-width contour could not be boxed alone)
  empty_group    no word or ayah-mark group without a path          (an empty ayah mark broke page 363's .qvp)
  orphan_hole    every wound-against outline sits in a path with its host   (a hole in another path than its letter is filled in)
  tajweed_marks  tajweed.json marks[word] has one class per diacritic path of that word, in order
  tajweed_span   every tajweed letter interval is inside the page and not empty
  unowned_left   no outline left without a word (the builder adopts one within 6 pt of a word; a left one is not drawn)
  tajweed_lines_dropped  lines whose tajweed letters were misplaced and dropped (reported, not an error of the SVG)
  decode         qvp-convert can read the .qvp back                  (when QVP_CONVERT is set)
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NUM = re.compile(r'-?\d+\.?\d*')
PATH_RE = re.compile(r'<path ([^>]*?) d="([^"]*)"')
WORD_RE = re.compile(r'<g class="word" data-word-key="([^"]+)"[^>]*>(.*?)</g>', re.S)
RING_RE = re.compile(r'<g class="ayah-mark"[^>]*data-ayah-key="([^"]+)">(.*?)</g>', re.S)


def _subpaths(d):
    out = []
    for part in re.split(r'(?=M)', d):
        n = [float(v) for v in NUM.findall(part)]
        if len(n) >= 6:
            pts = list(zip(n[0::2], n[1::2]))
            area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts))) / 2
            out.append((pts, area))
    return out


def _inside(pt, poly):
    x, y, c = pt[0], pt[1], False
    for i in range(len(poly)):
        (x1, y1), (x2, y2) = poly[i], poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def check_page(svg: str, tajweed: dict | None = None, stats: dict | None = None) -> dict[str, list[str]]:
    """{check name: [problems]} for one page's SVG text (plus its tajweed.json and builder stats when given)."""
    problems: dict[str, list[str]] = collections.defaultdict(list)
    try:
        ET.fromstring(svg)
    except ET.ParseError as exc:
        problems['xml'].append(str(exc))
        return dict(problems)
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    paths = [(a, d) for a, d in PATH_RE.findall(svg)]
    seen = collections.Counter(d for _a, d in paths)
    for d, n in seen.items():
        if not d.strip():
            problems['empty_path'].append(f'{n} paths without a d')
        elif n > 1:
            problems['duplicate_d'].append(f'{n}x {d[:50]}')
    for a, d in paths:
        nums = [float(v) for v in NUM.findall(d)]
        if len(nums) >= 4:
            w, h = max(nums[0::2]) - min(nums[0::2]), max(nums[1::2]) - min(nums[1::2])
            if w < 0.1 or h < 0.1:
                problems['thin_path'].append(f'{w:.2f}x{h:.2f} {d[:50]}')
    word_marks = {}
    for m in WORD_RE.finditer(svg):
        ps = PATH_RE.findall(m.group(2))
        if not ps:
            problems['empty_group'].append(f'word {m.group(1)}')
            continue
        # a hole (an outline wound against the others) must share its path with an outline that surrounds it:
        # in a path of its own, or away from its letter, it is filled in
        for i, (_a, d) in enumerate(ps):
            subs = _subpaths(d)
            for pts, area in subs:
                if area >= -1.0:                              # a sliver under 1 pt2 is not a counter
                    continue
                cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
                if not any(a2 > 0 and min(q[0] for q in p2) <= cx <= max(q[0] for q in p2)
                           and min(q[1] for q in p2) <= cy <= max(q[1] for q in p2) for p2, a2 in subs):
                    problems['orphan_hole'].append(f'{m.group(1)}: a hole in path {i} with no outline around it in that path')
                    break
        word_marks[m.group(1)] = sum(1 for a, _d in ps if 'data-mark-family="diacritic"' in a)
    for m in RING_RE.finditer(svg):
        if not PATH_RE.findall(m.group(2)):
            problems['empty_group'].append(f'ayah mark {m.group(1)}')
    if tajweed is not None:
        for key, classes in tajweed.get('marks', {}).items():
            if word_marks.get(key, 0) != len(classes):
                problems['tajweed_marks'].append(f'{key}: {word_marks.get(key, 0)} diacritic paths, {len(classes)} classes')
        for key, spans in tajweed.get('letters', {}).items():
            for x0, x1, _cls in spans:
                if not (-3 <= x0 < x1 <= vb[2] + 3 and x1 - x0 <= 60):
                    problems['tajweed_span'].append(f'{key}: [{x0}, {x1}] outside the page or wider than 60 pt')
    if stats is not None:
        if stats.get('unowned_left'):                    # ink the builder could not give to any word (it is not drawn)
            problems['unowned_left'].append(f'{len(stats["unowned_left"])} outlines, first {stats["unowned_left"][0]}')
        if stats.get('tj_bad_lines'):                    # lines whose tajweed letters were dropped as misplaced
            problems['tajweed_lines_dropped'].append(f'lines {stats["tj_bad_lines"]}')
    return dict(problems)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    svg_dir = ROOT / 'artifacts' / 'shamarly-qvp' / 'svg'
    qvp_dir = ROOT / 'artifacts' / 'shamarly-qvp' / 'qvp'
    for i, a in enumerate(sys.argv):
        if a == '--svg-dir':
            svg_dir = Path(sys.argv[i + 1])
            args = [x for x in args if x != sys.argv[i + 1]]
        if a == '--qvp-dir':
            qvp_dir = Path(sys.argv[i + 1])
            args = [x for x in args if x != sys.argv[i + 1]]
    pages = sorted(int(p) for p in args) or sorted(int(p.stem) for p in svg_dir.glob('???.svg'))
    binary = os.environ.get('QVP_CONVERT')
    totals, failed = collections.Counter(), []
    for n in pages:
        svg = (svg_dir / f'{n:03d}.svg').read_text(encoding='utf-8')
        tj_path, st_path = svg_dir / f'{n:03d}.tajweed.json', svg_dir / f'{n:03d}.json'
        found = check_page(svg, json.loads(tj_path.read_text(encoding='utf-8')) if tj_path.exists() else None,
                           json.loads(st_path.read_text(encoding='utf-8')) if st_path.exists() else None)
        qvp = qvp_dir / f'{n:03d}.qvp'
        if binary and qvp.exists():
            r = subprocess.run([binary, 'info', str(qvp)], capture_output=True, text=True)
            if r.returncode:
                found.setdefault('decode', []).append((r.stderr.strip().splitlines() or ['?'])[-1][:80])
        for name, items in found.items():
            totals[name] += len(items)
        if found:
            failed.append((n, found))
    print(f'{len(pages)} pages checked, {len(failed)} with problems')
    for name, count in totals.most_common():
        print(f'  {name}: {count}')
    for n, found in failed[:15]:
        for name, items in found.items():
            print(f'  page {n:03d} {name}: {items[0]}' + (f' (+{len(items) - 1})' if len(items) > 1 else ''))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
