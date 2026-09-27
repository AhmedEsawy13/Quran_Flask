#!/usr/bin/env python3
"""Store each classical ruling's العلّة (`illa`) and, for a «ومثله / وكذا»
item, the ruling it follows (`follows`), in data/classical_waqf.db.

    python3 pipeline/derive_illa.py            # all four books (idempotent)

Run it last, after any book's rebuild and audits. A row's `note` is the book
text beside its quote; core/classical_illa.split() keeps only the reason. Whether
a row is a chain item — and which ruling heads the chain — comes from the book
itself:
  · منار: pipeline/audit_manar_mithl.audit() (every «ومثله / وكذا» item and its head);
  · المكتفى: the «{…}» quotes of each surah in book order; an item is a chain
    item when «ومثله / وكذا / وكذلك» introduces it, its head the last quote
    before the run that was not;
  · ابن الأنباري / النحاس: the note starts before the quote (audit_anbari
    renote; nahhas_parse notes), so split() sees the chain word, and the head
    is the row just before it in book order (core/classical_illa.chain_head).
A chain item with no reason of its own shows its head's.
"""
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import logging
logging.disable(logging.INFO)
import build_classical_waqf as rx                       # noqa: E402
from core.classical_illa import split, chain_head, _plain, _ADDED   # noqa: E402

DB = os.path.join(os.path.dirname(HERE), 'data', 'classical_waqf.db')
_CHAIN_BEFORE = re.compile(r'(?:و?مثله|و?مثلها|و?كذا|و?كذلك|ونظيره)\s*[:،]?\s*$')


def ensure_columns(con):
    cols = {r[1] for r in con.execute('PRAGMA table_info(classical)')}
    for c in ('illa', 'follows'):
        if c not in cols:
            con.execute(f'ALTER TABLE classical ADD COLUMN {c} TEXT')


def _fmt(quote, ayah):
    return f'{_plain(quote)} ({ayah})' if ayah else _plain(quote)


def manar_chains(con):
    """{row id: head row id} for منار chain items."""
    import audit_manar_mithl as mm
    recs = mm.audit(mm.load_db(DB))
    out = {}
    for r in recs:
        if 'ayah' not in r or r.get('status') not in ('ok', 'grade_mismatch'):
            continue
        item = con.execute("SELECT id FROM classical WHERE source='manar' AND surah=? AND ayah=? AND wpos=? "
                           "AND grade=? AND conf=1", (r['surah'], r['ayah'], r['wpos'], r['grade'])).fetchone()
        hw = mm.head_seat(r['surah'], r['head_ayah'], r['head'])
        head = hw is not None and con.execute(
            "SELECT id FROM classical WHERE source='manar' AND surah=? AND ayah=? AND wpos=? AND grade=? "
            "AND conf=1", (r['surah'], r['head_ayah'], hw, r['head_grade'])).fetchone()
        if item and head and item[0] != head[0] and r['grade'] == r['head_grade']:
            out[item[0]] = head[0]
    return out


def muktafa_chains(con):
    """{row id: head row id} for المكتفى chain items, from the book's quotes."""
    body = rx.normalize_muktafa_headings(rx.load_book(rx.SOURCES['muktafa']))
    texts, last = {}, 0
    for sec in re.split(r'\n### \| ', body):
        t, _, x = sec.partition('\n')
        if 'سورة' not in t and 'أم القرآن' not in t:
            continue
        n = rx.surah_number(t, last)
        if n:
            last = n
            texts[n] = texts.get(n, '') + '\n' + _plain(x)
    out = {}
    for surah, text in texts.items():
        occ = []                                   # (plain quote, is chain item)
        prev_end = 0
        for m in re.finditer(r'\{([^{}]{1,160})\}|\(\(([^()]{1,160})\)\)', text):
            occ.append((re.sub(r'\s+', ' ', m.group(1) or m.group(2)).strip(),
                        bool(_CHAIN_BEFORE.search(text[prev_end:m.start()].rstrip(' .'))), m.start()))
            prev_end = m.end()
        rows = con.execute("SELECT id, quote, grade FROM classical WHERE source='muktafa' AND surah=? AND conf=1 "
                           "AND grade_raw NOT IN ('رؤوس الآي') ORDER BY seq, id", (surah,)).fetchall()
        k = 0
        placed = []                                # (occurrence index, row id, grade)
        for rid, quote, grade in rows:
            q = re.sub(r'\s+', ' ', _plain(quote)).strip()
            for j in range(k, min(len(occ), k + 40)):
                if occ[j][0] == q:
                    placed.append((j, rid, grade))
                    k = j + 1
                    break
        by_occ = {j: (rid, grade) for j, rid, grade in placed}
        for j, rid, grade in placed:
            if not occ[j][1]:
                continue
            h = j - 1
            while h >= 0 and occ[h][1]:
                h -= 1
            if h >= 0 and h in by_occ and by_occ[h][1] == grade:
                out[rid] = by_occ[h][0]
    return out


def derive(con):
    ensure_columns(con)
    con.row_factory = sqlite3.Row
    heads = {**manar_chains(con), **muktafa_chains(con)}
    rows = con.execute('SELECT * FROM classical').fetchall()
    byid = {r['id']: r for r in rows}
    reason = {}
    chainy = {}
    for r in rows:
        reason[r['id']], chainy[r['id']] = split(r['note'], r['quote'], r['grade_raw'])
    updates = []
    for r in rows:
        own = reason[r['id']]
        follows = None
        if r['source'] in ('manar', 'muktafa'):
            hid = heads.get(r['id'])
            if hid:
                h = byid[hid]
                follows = _fmt(h['quote'] if r['source'] == 'muktafa' else h['stop_word'], h['ayah'])
                own = own or reason[hid]
        elif chainy[r['id']] and r['grade_raw'] not in _ADDED and r['conf'] == 1:
            head = chain_head(con, r)
            if head:
                follows = _fmt(head[0], head[1])
                own = own or head[2]
        updates.append((own, follows, r['id']))
    con.executemany('UPDATE classical SET illa=?, follows=? WHERE id=?', updates)
    con.commit()
    return len(updates), sum(1 for u in updates if u[1]), sum(1 for u in updates if u[0])


def main():
    con = sqlite3.connect(DB)
    n, chained, with_reason = derive(con)
    print(f'{n} rows: {chained} follow a head, {with_reason} with an علّة')
    con.close()


if __name__ == '__main__':
    main()
