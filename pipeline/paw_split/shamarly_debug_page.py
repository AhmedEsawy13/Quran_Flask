"""Debug pictures of a built Shamarly page (artifacts/shamarly-qvp/svg/NNN.svg): colour makes ownership bugs visible.

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_debug_page.py 4 42 100
        -> artifacts/shamarly-qvp/debug/NNN-words.png   and   NNN-tajweed.png

words    every word a hue of its own (neighbours always differ); the small outlines of a word (harakat, dots, hamza) are
         drawn in the OPPOSITE hue of that word, so a mark that belongs to the neighbour shows up in the wrong colour;
         waqf signs are magenta, verse rings grey, a word whose outline-count check failed gets a thin red underline, an
         outline the builder had to give to the nearest word (nobody owned it) gets a cyan box.
tajweed  what the reader draws with the colours on: tajweed-coloured mark paths, and the letters the rules colour (the
         x-intervals of NNN.tajweed.json clip the word's bodies), in the reader's own class colours.
"""
from __future__ import annotations

import colorsys
import json
import re
import sys
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shamarly_mix_render as R  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts' / 'shamarly-qvp' / 'debug'
SCALE = 3

TAJWEED = {'madda_normal': '#b45353', 'madda_permissible': '#a33b2b', 'madda_munfasil': '#a33b2b',
           'madda_obligatory': '#8e2a1e', 'madda_necessary': '#6e1a14', 'ghunnah': '#246a40', 'iqlab': '#246a40',
           'idgham_ghunnah': '#246a40', 'ikhafa': '#2f8052', 'ikhafa_shafawi': '#2f8052', 'idgham_wo_ghunnah': '#175b34',
           'idgham_shafawi': '#175b34', 'idgham_mutajanisayn': '#175b34', 'idgham_mutaqaribayn': '#175b34',
           'qalaqah': '#2852b4'}


def hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return f'#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}'


def parse(text):
    """[(kind, payload)] in document order: ('word', key, [(attrs, d)]), ('ring', key, [d]); plus viewBox."""
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', text).group(1).split()]
    items = []
    for m in re.finditer(r'<g class="word" data-word-key="([^"]+)"[^>]*>(.*?)</g>|<g class="ayah-mark"[^>]*data-ayah-key="([^"]+)">(.*?)</g>', text, re.S):
        if m.group(1):
            items.append(('word', m.group(1), R.PATH.findall(m.group(2))))
        else:
            items.append(('ring', m.group(3), [(a, d) for a, d in R.PATH.findall(m.group(4))]))
    return vb, items


def raster(svg, vb, name):
    import fitz
    doc = fitz.open(stream=svg.encode(), filetype='svg')
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
    pix.save(str(OUT / name))


def words_picture(n):
    text = (R.SVG_DIR / f'{n:03d}.svg').read_text(encoding='utf-8')
    stats = json.loads((R.SVG_DIR / f'{n:03d}.json').read_text(encoding='utf-8'))
    off = set(stats.get('count_off', []))
    vb, items = parse(text)
    out, k = [], 0
    for kind, key, paths in items:
        if kind == 'ring':
            out.append(f'<g fill="#9a9a9a">{"".join(f"<path d=\"{d}\"/>" for _a, d in paths)}</g>')
            continue
        hue = (k * 0.381966) % 1.0                                   # golden-ratio steps: neighbours never look alike
        k += 1
        body, marks, signs = [], [], []
        for a, d in paths:
            if 'data-mark-family="waqf"' in a:
                signs.append(d)
            elif R._small(R.bbox(d)) or 'data-mark-family="diacritic"' in a:
                marks.append(d)
            else:
                body.append(d)
        out.append(f'<g fill="{hsl(hue, .65, .30)}">{"".join(f"<path d=\"{d}\"/>" for d in body)}</g>')
        out.append(f'<g fill="{hsl(hue + .5, .95, .42)}">{"".join(f"<path d=\"{d}\"/>" for d in marks)}</g>')
        out.append(f'<g fill="#d400d4">{"".join(f"<path d=\"{d}\"/>" for d in signs)}</g>')
        if key in off:
            allb = [R.bbox(d) for _a, d in paths if 'waqf' not in _a]
            if allb:
                x0, x1, y = min(b[0] for b in allb), max(b[2] for b in allb), max(b[3] for b in allb) + 1.5
                out.append(f'<rect x="{x0:.1f}" y="{y:.1f}" width="{x1 - x0:.1f}" height="0.9" fill="#e02020"/>')
    for _oid, _key, b in stats.get('adopted', []):                 # outlines nobody owned, given to the nearest word
        out.append(f'<rect x="{b[0] - 1.5:.1f}" y="{b[1] - 1.5:.1f}" width="{b[2] - b[0] + 3:.1f}" height="{b[3] - b[1] + 3:.1f}" '
                   f'fill="none" stroke="#00b8d9" stroke-width="0.7"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}" width="{vb[2] * SCALE:.0f}" '
           f'height="{vb[3] * SCALE:.0f}"><rect x="{vb[0]}" y="{vb[1]}" width="{vb[2]}" height="{vb[3]}" fill="#fbfaf6"/>{"".join(out)}</svg>')
    raster(svg, vb, f'{n:03d}-words.png')


def tajweed_picture(n):
    text = (R.SVG_DIR / f'{n:03d}.svg').read_text(encoding='utf-8')
    tj = json.loads((R.SVG_DIR / f'{n:03d}.tajweed.json').read_text(encoding='utf-8'))
    vb, items = parse(text)
    out, clips = [], []
    for kind, key, paths in items:
        if kind == 'ring':
            out.append(f'<g fill="#1a1a1a">{"".join(f"<path d=\"{d}\"/>" for _a, d in paths)}</g>')
            continue
        classes = list(tj['marks'].get(key, []))
        body = [d for a, d in paths if 'data-kind="body"' in a]
        out.append(f'<g fill="#1a1a1a">{"".join(f"<path d=\"{d}\"/>" for d in body)}</g>')
        for a, d in paths:
            if 'data-mark-family="diacritic"' in a:
                cls = classes.pop(0) if classes else None
                out.append(f'<path d="{d}" fill="{TAJWEED.get(cls, "#ff00ff")}"/>')
            elif 'data-mark-family="waqf"' in a:
                out.append(f'<path d="{d}" fill="#1a1a1a"/>')
        for i, (x0, x1, cls) in enumerate(tj['letters'].get(key, [])):          # page-space x, the viewBox starts at vb[0]
            cid = f'c{len(clips)}'
            clips.append(f'<clipPath id="{cid}"><rect x="{x0 + vb[0]:.2f}" y="{vb[1]}" width="{x1 - x0:.2f}" height="{vb[3]}"/></clipPath>')
            out.append(f'<g clip-path="url(#{cid})" fill="{TAJWEED.get(cls, "#ff00ff")}">{"".join(f"<path d=\"{d}\"/>" for d in body)}</g>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb[0]} {vb[1]} {vb[2]} {vb[3]}" width="{vb[2] * SCALE:.0f}" '
           f'height="{vb[3] * SCALE:.0f}"><defs>{"".join(clips)}</defs><rect x="{vb[0]}" y="{vb[1]}" width="{vb[2]}" height="{vb[3]}" fill="#fbfaf6"/>{"".join(out)}</svg>')
    raster(svg, vb, f'{n:03d}-tajweed.png')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        n = int(arg)
        words_picture(n)
        tajweed_picture(n)
        print('page', n, 'written')


if __name__ == '__main__':
    main()
