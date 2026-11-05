"""Build a small Kraken fine-tuning set from the Shamarly vector PDF: line crops + PageXML with the known text.

One 300-dpi crop and one PageXML per ayah line, the line given to Kraken the same way inference gives it
(a baseline two thirds down the crop, the whole crop as boundary), so training sees what the aligner sees.
The text is the line text from ShemrlyMushaf's batch-rest report with the parts the print does not carry as
letters removed: the verse number (it sits inside the ring) and the waqf signs (drawn apart, above the words).
Pages used by the pipeline-eval ground truth are never included.

    ~/Development/ShemrlyMushaf/.venv/bin/python pipeline/paw_split/shamarly_kraken_trainset.py OUT_DIR \\
        [--pages N --val 8]
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path

import pymupdf
from html import escape

from PIL import Image

SH = Path('/Users/mac/Development/ShemrlyMushaf')
EVAL = {204, 212, 219, 245, 251, 337, 371, 373, 481}
Z = 300 / 72
DIGITS = set('٠١٢٣٤٥٦٧٨٩0123456789۰۱۲۳۴۵۶۷۸۹۝')
WAQF = set('ۖۗۘۙۚۛۜ۞۩')


def clean(text: str) -> str:
    words = []
    for tok in text.split():
        if all(c in DIGITS for c in tok):
            continue
        tok = ''.join(c for c in tok if c not in WAQF and c not in DIGITS and c != 'ـ')
        if tok:
            words.append(tok)
    return ' '.join(words)


PAGE_NS = 'http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15'


def page_xml(png: Path, w: int, h: int, baseline_y: int, text: str) -> str:
    """PageXML for one line crop: the whole crop is the line, the baseline two thirds down (as at inference)."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PcGts xmlns="{PAGE_NS}">
  <Metadata><Creator>shamarly_kraken_trainset</Creator></Metadata>
  <Page imageFilename="{escape(str(png))}" imageWidth="{w}" imageHeight="{h}">
    <TextRegion id="r1">
      <Coords points="0,0 {w},0 {w},{h} 0,{h}"/>
      <TextLine id="l1" readingDirection="right-to-left">
        <Coords points="2,2 {w - 3},2 {w - 3},{h - 3} 2,{h - 3}"/>
        <Baseline points="2,{baseline_y} {w - 2},{baseline_y}"/>
        <TextEquiv><Unicode>{escape(text)}</Unicode></TextEquiv>
      </TextLine>
    </TextRegion>
  </Page>
</PcGts>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--pages', type=int, default=54)
    ap.add_argument('--val', type=int, default=8, help='pages held out whole for validation')
    ap.add_argument('--stride', type=int, default=6)
    a = ap.parse_args()
    out = Path(a.out)
    (out / 'xml').mkdir(parents=True, exist_ok=True)
    allp = sorted(int(p.name[5:]) for p in (SH / 'output/pdf/batch-rest').glob('page-*'))
    pages = [p for p in allp if p not in EVAL][::a.stride][:a.pages]
    val_pages = set(pages[::max(1, len(pages) // a.val)][:a.val])
    doc = pymupdf.open(SH / 'BOOK_27111_1.pdf')
    lists = {'train': [], 'val': []}
    n_lines = chars = 0
    for n in pages:
        rep = json.load(open(SH / f'output/pdf/batch-rest/page-{n:03d}/report.json'))
        pg = doc[n - 1]
        for l in rep['lines']:
            if l['line_type'] != 'ayah':
                continue
            text = clean(l['text'])
            if not text:
                continue
            x0, y0, x1, y1 = l['bbox']
            name = f'p{n:03d}_l{l["line_number"]:02d}'
            png = out / f'{name}.png'
            pg.get_pixmap(clip=pymupdf.Rect(x0 - 3, y0 - 2, x1 + 3, y1 + 2), matrix=pymupdf.Matrix(Z, Z),
                          alpha=False).save(png)
            w, h = Image.open(png).size
            by = int(0.66 * h)
            xml = out / 'xml' / f'{name}.xml'
            xml.write_text(page_xml(png, w, h, by, text), encoding='utf-8')
            lists['val' if n in val_pages else 'train'].append(str(xml))
            n_lines += 1
            chars += len(text)
    for k, v in lists.items():
        (out / f'{k}.txt').write_text('\n'.join(v) + '\n')
    json.dump({'pages': pages, 'val_pages': sorted(val_pages), 'train_lines': len(lists['train']),
               'val_lines': len(lists['val'])}, open(out / 'manifest.json', 'w'))
    print(f'{len(pages)} pages ({len(val_pages)} held out), lines train {len(lists["train"])} val {len(lists["val"])}, '
          f'{chars} characters')


if __name__ == '__main__':
    main()
