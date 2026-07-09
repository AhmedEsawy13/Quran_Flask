#!/usr/bin/env python3
"""Build data/tafseer_local.db — local copies of all five tafsirs shown on
the reading page, from Quranic Universal Library (QUL) exports.

Replaces the former per-request live calls in modules/reading.py's
get_tafseer(): every /api/tafseer/<surah>/<ayah> request fired up to 5
parallel outbound HTTP calls (4x api.quran.com + 1x quranenc.com), each with
a 10s timeout — on a single-worker/4-thread dyno, a handful of concurrent
users hitting uncached verses could tie up every request-handling thread at
once, making the whole app unresponsive. Harvesting once at build time (the
same move build_tajweed_local.py already made for tajweed coloring) removes
tafseer from the request path entirely.

Inputs: the 5 tafsir SQLite exports downloaded manually from QUL (each
resource's "Download sqlite" button requires a free QUL account — not
scriptable), placed in pipeline/tafseer_source/ (gitignored, not vendored —
these are ~65MB total, much larger than tajweed's vendored source):
  ar-tafseer-al-saddi.db                                  (تفسير السعدي)
  ar-tafseer-al-qurtubi.db                                (تفسير القرطبي)
  ar-tafsir-al-baghawi.db                                 (تفسير البغوي)
  ar-tafsir-muyassar.db                                   (التفسير الميسر)
  arabic-al-mukhtasar-in-interpreting-the-noble-quran.db  (المختصر في التفسير)
Source: https://qul.tarteel.ai/resources/tafsir?tags[]=Arabic

Each export is a single `tafsir` table: (ayah_key, group_ayah_key, from_ayah,
to_ayah, ayah_keys, text) — one row per ayah_key (always exactly 6236, one
per Quran ayah), but a tafsir that discusses several ayat together (common
in Qurtubi/Baghawi — e.g. Baghawi covers all of al-Fatiha, 1:1-1:7, under a
single heading) stores the actual text ONLY on the row whose ayah_key equals
its own group_ayah_key; every other ayah_key in that group has an EMPTY text
column and just points at group_ayah_key. Storing the FULL text redundantly
under every member ayah_key (the simplest schema) would have worked but
bloats data/tafseer_local.db to ~137MB — measured: deduplicated (storing
each group's text exactly once) the same content is ~31MB of text, so the
output table instead keeps text only on each group's representative row and
lets a second, cheap indexed lookup (modules/reading.py's
get_local_tafseer()) resolve member ayat to it.

    python3 pipeline/build_tafseer_local.py

Tafsir texts rarely change once published — this is a one-time harvest,
re-run only if QUL updates a source or a new tafsir is added.
"""
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, 'pipeline', 'tafseer_source')
OUT_DB = os.path.join(BASE, 'data', 'tafseer_local.db')

# app-facing name -> source filename (names match TAFSEER_API_IDS /
# TAFSEER_QURANENC_IDS keys already used in modules/reading.py, so the
# app-side dict lookup needs no changes beyond the data source itself).
SOURCES = {
    'تفسير السعدي': 'ar-tafseer-al-saddi.db',
    'تفسير القرطبي': 'ar-tafseer-al-qurtubi.db',
    'تفسير البغوي': 'ar-tafsir-al-baghawi.db',
    'التفسير الميسر': 'ar-tafsir-muyassar.db',
    'المختصر في التفسير': 'arabic-al-mukhtasar-in-interpreting-the-noble-quran.db',
}


def harvest_one(name, path):
    """Returns (verse_rows, group_rows) — verse_rows is [(name, verse_key,
    group_key), ...] for every ayah_key (member ayat point at their group's
    representative verse_key; representative rows point at themselves),
    group_rows is [(name, group_key, text), ...] with text stored exactly
    once per group."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT ayah_key, group_ayah_key, text FROM tafsir')
    raw = cur.fetchall()
    conn.close()

    group_has_text = {r['ayah_key'] for r in raw if r['text']}

    verse_rows, group_rows = [], []
    missing = 0
    for r in raw:
        gk = r['group_ayah_key']
        if gk not in group_has_text:
            missing += 1
            continue
        verse_rows.append((name, r['ayah_key'], gk))
        if r['text']:
            group_rows.append((name, gk, r['text']))
    print(f'  {name}: {len(verse_rows)}/6236 ayat, {len(group_rows)} distinct groups '
          f'({missing} with no source text)')
    return verse_rows, group_rows


def main():
    missing_sources = [f for f in SOURCES.values() if not os.path.exists(os.path.join(SRC, f))]
    if missing_sources:
        raise SystemExit(
            f'Missing source file(s) in {SRC}: {missing_sources}\n'
            'Download each tafsir\'s SQLite export from '
            'https://qul.tarteel.ai/resources/tafsir?tags[]=Arabic (requires a free '
            'QUL account) and place it there before running this script.'
        )

    verse_rows, group_rows = [], []
    print('Harvesting local QUL tafsir exports...')
    for name, filename in SOURCES.items():
        v, g = harvest_one(name, os.path.join(SRC, filename))
        verse_rows.extend(v)
        group_rows.extend(g)

    os.makedirs(os.path.dirname(OUT_DB), exist_ok=True)
    if os.path.exists(OUT_DB):
        os.remove(OUT_DB)
    con = sqlite3.connect(OUT_DB)
    con.execute(
        'CREATE TABLE tafseer_verse (name TEXT NOT NULL, verse_key TEXT NOT NULL, '
        'group_key TEXT NOT NULL, PRIMARY KEY (name, verse_key))'
    )
    con.execute(
        'CREATE TABLE tafseer_group (name TEXT NOT NULL, group_key TEXT NOT NULL, '
        'text TEXT NOT NULL, PRIMARY KEY (name, group_key))'
    )
    con.executemany(
        'INSERT OR REPLACE INTO tafseer_verse (name, verse_key, group_key) VALUES (?, ?, ?)',
        verse_rows
    )
    con.executemany(
        'INSERT OR REPLACE INTO tafseer_group (name, group_key, text) VALUES (?, ?, ?)',
        group_rows
    )
    con.commit()
    con.close()
    print(f'\nwrote {len(verse_rows)} verse mappings + {len(group_rows)} group texts to {OUT_DB}')
    print('commit data/tafseer_local.db so deployments ship it — no more live tafseer API calls.')


if __name__ == '__main__':
    main()
