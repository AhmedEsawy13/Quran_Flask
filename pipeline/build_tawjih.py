#!/usr/bin/env python3
"""Align contemporary توجيه (د. أحمد صابر, @Dr_ahmed21) to QPC word positions.

Not a fifth classical book. Never writes `data/classical_waqf.db`.

Policy (no inferred grades or verses):
  * skip retweets, Zoom, WhatsApp, event announcements, and empty bodies;
  * replies use `reply_text`;
  * publish only an explicit Quran quote with a unique exact/prefix QPC match;
  * set grade only when تام/كاف/حسن/جائز/قبيح/لازم/لا يوقف is explicit;
  * `related_waqf` is not a publish filter.

Reads `public.dr_ahmed21_posts` and upserts `public.tawjih` when Supabase is
configured. `--sqlite` writes `data/tawjih.db` for tests / offline fallback.

Run:
  python3 pipeline/build_tawjih.py              # dry-run stats
  python3 pipeline/build_tawjih.py --write      # upsert Supabase
  python3 pipeline/build_tawjih.py --sqlite data/tawjih.db --write
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

from core import supabase_editor as sb  # noqa: E402
from core.config import TAWJIH_DATABASE  # noqa: E402
from core.datasets import qpc_hafs_data_normalized  # noqa: E402
from core.tawjih import ensure_sqlite_schema, verse_words  # noqa: E402
from pipeline import build_classical_waqf as classical  # noqa: E402

SKIP_KINDS = frozenset({'إعادة تغريد'})
CANONICAL_GRADES = ('لا يوقف عليه', 'لا يوقف', 'لا وقف', 'لازم', 'تام', 'كاف', 'حسن', 'جائز', 'قبيح')
GRADE_CANON = {
    'لا يوقف عليه': 'لا',
    'لا يوقف': 'لا',
    'لا وقف': 'لا',
    'لازم': 'لازم',
    'تام': 'تام',
    'كاف': 'كاف',
    'حسن': 'حسن',
    'جائز': 'جائز',
    'قبيح': 'قبيح',
}

# Delimited explicit quotes only — never harvest a verse from surrounding prose.
_ORNAMENTAL_QUOTE_RE = re.compile(r'﴿\s*([^﴾]{2,240})\s*﴾')
_GUILLEMET_QUOTE_RE = re.compile(r'«\s*([^»]{2,240})\s*»')
_ATTRIBUTED_QUOTE_RE = re.compile(
    r'(?:قوله(?:\s+تعالى)?|الوقف\s+على|يوقف\s+على|وقف[^\n]{0,40}على)'
    r'\s*[:：]?\s*[«"“”]'
    r'([^»"”]{2,240})'
    r'[»"”]'
)
_AYAH_ONLY_RE = re.compile(r'آي[ةه]\s*([0-9٠-٩۰-۹]+)')
_SKIP_TEXT_RE = re.compile(
    r'zoom\.us|whatsapp\.com|\bwa\.me\b|\bzoom\b|زوم|'
    r'واتساب|واتس\s*أب|chat\.whatsapp|'
    r'لقاء بعنوان|شهادة حضور|للتسجيل',
    re.IGNORECASE,
)
_AR_DIGIT_TRANS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
_SURAH_AYAH_RE = re.compile(
    r'سورة\s+([^\s،,:]{2,30})(?:\s*[:：]?\s*آية\s*([0-9٠-٩۰-۹]+))?',
)
# Bare 10:30 (clock times) must not look like 10:30 the verse. Require سورة/آية.
_NUMERIC_REF_RE = re.compile(
    r'(?:سورة|آية)\s*([1-9][0-9]{0,2}|[١-٩][٠-٩]{0,2})\s*[:：]\s*([1-9][0-9]{0,2}|[١-٩][٠-٩]{0,2})'
)
_ARABIC_LETTER_RE = re.compile(r'[\u0600-\u06FF]')

_VERSE_INDEX: list[tuple[int, int, list[str]]] | None = None
_SURAH_NAMES: dict[str, int] | None = None


@dataclass(frozen=True)
class TawjihRow:
    tweet_id: str
    surah: int | None
    ayah: int | None
    wpos: int | None
    quote: str | None
    note: str
    grade: str | None
    status: str
    align_conf: int
    skip_reason: str | None
    locator: str
    url: str
    created_at: str | None


def post_body(post: dict) -> str:
    """Replies use reply_text; every other kind uses post_text."""
    if (post.get('kind') or '') == 'رد':
        return (post.get('reply_text') or '').strip()
    return (post.get('post_text') or '').strip()


def _has_arabic(text: str) -> bool:
    return bool(_ARABIC_LETTER_RE.search(text or ''))


def skip_reason_for(post: dict) -> str | None:
    kind = (post.get('kind') or '').strip()
    if kind in SKIP_KINDS:
        return 'retweet'
    body = post_body(post)
    if not body or not _has_arabic(body):
        return 'empty'
    if _SKIP_TEXT_RE.search(body):
        if re.search(r'zoom\.us|\bzoom\b|زوم', body, re.I):
            return 'zoom'
        if re.search(r'whatsapp|واتس', body, re.I):
            return 'whatsapp'
        return 'event'
    return None


def extract_quotes(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for rx in (_ORNAMENTAL_QUOTE_RE, _GUILLEMET_QUOTE_RE, _ATTRIBUTED_QUOTE_RE):
        for match in rx.finditer(text or ''):
            quote = (match.group(1) or '').strip()
            quote = re.sub(r'[٠-٩۰-۹0-9]+', ' ', quote)
            quote = re.sub(r'\s+', ' ', quote).strip()
            if not quote or not _has_arabic(quote):
                continue
            key = classical.norm(quote)
            if not key or key in seen:
                continue
            seen.add(key)
            found.append(quote)
    return found


def extract_grade(text: str) -> str | None:
    """Return a canonical grade only when exactly one explicit label is present."""
    hits: list[str] = []
    for raw in CANONICAL_GRADES:
        pattern = r'(?<![\u0600-\u06FF])' + re.escape(raw) + r'(?![\u0600-\u06FF])'
        if re.search(pattern, text or ''):
            hits.append(GRADE_CANON[raw])
    unique = list(dict.fromkeys(hits))
    if len(unique) == 1:
        return unique[0]
    return None


def _surah_name_map() -> dict[str, int]:
    global _SURAH_NAMES
    if _SURAH_NAMES is None:
        names = {classical.norm(name): num for name, num in classical.ALIASES.items()}
        try:
            import app as quran_app
            for surah in getattr(quran_app, 'surahs_data', []) or []:
                n = classical.norm(surah.get('name') or '')
                if n:
                    names[n] = int(surah['number'])
                    if n.startswith('ال') and len(n) > 3:
                        names[n[2:]] = int(surah['number'])
        except Exception:
            pass
        _SURAH_NAMES = names
    return _SURAH_NAMES


def parse_verse_locator(text: str) -> tuple[int | None, int | None]:
    """Explicit سورة / N:N locator only. Never guessed from the quote."""
    if not text:
        return None, None
    mapped = _surah_name_map()
    match = _SURAH_AYAH_RE.search(text)
    if match:
        name = classical.norm(match.group(1))
        surah = mapped.get(name)
        ayah = None
        if match.group(2):
            try:
                ayah = int(match.group(2).translate(_AR_DIGIT_TRANS))
            except ValueError:
                ayah = None
        if surah:
            if ayah is None:
                ayah_only = _AYAH_ONLY_RE.search(text)
                if ayah_only:
                    try:
                        ayah = int(ayah_only.group(1).translate(_AR_DIGIT_TRANS))
                    except ValueError:
                        ayah = None
            return surah, ayah
    num = _NUMERIC_REF_RE.search(text)
    if num:
        try:
            surah = int(num.group(1).translate(_AR_DIGIT_TRANS))
            ayah = int(num.group(2).translate(_AR_DIGIT_TRANS))
        except ValueError:
            return None, None
        if 1 <= surah <= 114 and ayah >= 1:
            return surah, ayah
    return None, None


def _verse_index() -> list[tuple[int, int, list[str]]]:
    global _VERSE_INDEX
    if _VERSE_INDEX is None:
        index = []
        for key in qpc_hafs_data_normalized:
            try:
                surah_s, ayah_s = key.split(':')
                surah, ayah = int(surah_s), int(ayah_s)
            except ValueError:
                continue
            words = verse_words(surah, ayah)
            if not words:
                continue
            index.append((surah, ayah, [classical.norm(w) for w in words]))
        index.sort()
        _VERSE_INDEX = index
    return _VERSE_INDEX


def align_quote(
    quote: str,
    *,
    restrict_surah: int | None = None,
    restrict_ayah: int | None = None,
) -> list[tuple[int, int, int, int]]:
    """Exact/prefix matches of the full quoted span.

    Each hit is ``(surah, ayah, start_wpos, end_wpos)``. ``end_wpos`` is the
    stop word (last quoted token). No fuzzy / suffix fallback.
    """
    quoted = classical.quote_words(quote)
    if not quoted:
        return []
    hits: list[tuple[int, int, int, int]] = []
    for surah, ayah, verse in _verse_index():
        if restrict_surah is not None and surah != restrict_surah:
            continue
        if restrict_ayah is not None and ayah != restrict_ayah:
            continue
        length = len(quoted)
        if length > len(verse):
            continue
        for start in range(0, len(verse) - length + 1):
            if all(classical.match_word(quoted[i], verse[start + i], level=1)
                   for i in range(length)):
                hits.append((surah, ayah, start, start + length - 1))
    return hits


def _skipped(post: dict, reason: str, body: str = '') -> TawjihRow:
    return TawjihRow(
        tweet_id=str(post.get('tweet_id') or ''),
        surah=None, ayah=None, wpos=None, quote=None,
        note=body or post_body(post),
        grade=None, status='skipped', align_conf=0,
        skip_reason=reason,
        locator=f"tweet:{post.get('tweet_id') or ''}",
        url=post.get('url') or '',
        created_at=post.get('posted_at'),
    )


def classify_post(post: dict) -> list[TawjihRow]:
    """Turn one archive post into tawjih rows. related_waqf is ignored."""
    tweet_id = str(post.get('tweet_id') or '')
    body = post_body(post)
    reason = skip_reason_for(post)
    if reason:
        return [_skipped(post, reason, body)]

    quotes = extract_quotes(body)
    if not quotes:
        return [_skipped(post, 'no_quote', body)]

    loc_surah, loc_ayah = parse_verse_locator(body)
    grade = extract_grade(body)
    locator = f"tweet:{tweet_id}"
    rows: list[TawjihRow] = []
    for quote in quotes:
        hits = align_quote(quote, restrict_surah=loc_surah, restrict_ayah=loc_ayah)
        if not hits:
            rows.append(TawjihRow(
                tweet_id=tweet_id, surah=loc_surah, ayah=loc_ayah, wpos=None,
                quote=quote, note=body, grade=grade, status='review',
                align_conf=0, skip_reason='unaligned_quote', locator=locator,
                url=post.get('url') or '', created_at=post.get('posted_at'),
            ))
            continue
        unique_verses = {(s, a) for s, a, _start, _end in hits}
        unique_spans = {(s, a, end) for s, a, _start, end in hits}
        if len(unique_spans) == 1:
            surah, ayah, wpos = next(iter(unique_spans))
            rows.append(TawjihRow(
                tweet_id=tweet_id, surah=surah, ayah=ayah, wpos=wpos,
                quote=quote, note=body, grade=grade, status='published',
                align_conf=1, skip_reason=None, locator=locator,
                url=post.get('url') or '', created_at=post.get('posted_at'),
            ))
        elif loc_ayah is None and len(unique_verses) > 1:
            rows.append(TawjihRow(
                tweet_id=tweet_id, surah=loc_surah, ayah=None, wpos=None,
                quote=quote, note=body, grade=grade, status='review',
                align_conf=0, skip_reason='ambiguous_verse', locator=locator,
                url=post.get('url') or '', created_at=post.get('posted_at'),
            ))
        else:
            rows.append(TawjihRow(
                tweet_id=tweet_id, surah=loc_surah, ayah=loc_ayah, wpos=None,
                quote=quote, note=body, grade=grade, status='review',
                align_conf=0, skip_reason='ambiguous_repeated_phrase',
                locator=locator, url=post.get('url') or '',
                created_at=post.get('posted_at'),
            ))
    return rows or [_skipped(post, 'no_quote', body)]


def classify_posts(posts: Iterable[dict]) -> list[TawjihRow]:
    out: list[TawjihRow] = []
    for post in posts:
        out.extend(classify_post(post))
    return out


def row_payload(row: TawjihRow) -> dict:
    payload = asdict(row)
    payload.pop('url', None)
    payload.pop('created_at', None)
    return payload


def write_sqlite(path: Path, rows: list[TawjihRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        ensure_sqlite_schema(conn)
        conn.execute('DELETE FROM tawjih')
        conn.executemany(
            'INSERT INTO tawjih ('
            'tweet_id,surah,ayah,wpos,quote,note,grade,status,align_conf,'
            'skip_reason,locator,url,created_at) '
            'VALUES (:tweet_id,:surah,:ayah,:wpos,:quote,:note,:grade,:status,'
            ':align_conf,:skip_reason,:locator,:url,:created_at)',
            [asdict(row) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()


def fetch_posts() -> list[dict]:
    if not sb.is_configured():
        raise RuntimeError('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required')
    out: list[dict] = []
    page = 1000
    offset = 0
    select = (
        'tweet_id,seq,posted_at,kind,post_text,reply_text,url,related_waqf'
    )
    while True:
        batch = sb._request(
            'GET',
            'dr_ahmed21_posts',
            params={
                'select': select,
                'order': 'seq.asc.nullslast',
                'limit': str(page),
                'offset': str(offset),
            },
        ) or []
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


def upsert_supabase(rows: list[TawjihRow], batch_size: int = 200) -> None:
    if not sb.is_configured():
        raise RuntimeError('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required')
    payloads = [row_payload(row) for row in rows]
    for start in range(0, len(payloads), batch_size):
        chunk = payloads[start:start + batch_size]
        sb._request(
            'POST',
            'tawjih',
            params={'on_conflict': 'tweet_id,surah,ayah,wpos'},
            json_body=chunk,
            prefer='resolution=merge-duplicates,return=minimal',
        )


def _stats(rows: list[TawjihRow]) -> dict[str, int]:
    counts = {
        'rows': len(rows),
        'published': 0,
        'review': 0,
        'skipped': 0,
    }
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true',
                        help='upsert aligned rows (otherwise dry-run)')
    parser.add_argument('--sqlite', type=Path, default=None,
                        help='optional sqlite fallback path (tests / offline)')
    parser.add_argument('--from-sqlite-posts', type=Path, default=None,
                        help='read posts from a local sqlite table dr_ahmed21_posts')
    args = parser.parse_args(argv)

    if args.from_sqlite_posts:
        conn = sqlite3.connect(args.from_sqlite_posts)
        conn.row_factory = sqlite3.Row
        try:
            posts = [dict(r) for r in conn.execute(
                'SELECT tweet_id,seq,posted_at,kind,post_text,reply_text,url,related_waqf '
                'FROM dr_ahmed21_posts ORDER BY seq'
            )]
        finally:
            conn.close()
    else:
        posts = fetch_posts()

    rows = classify_posts(posts)
    stats = _stats(rows)
    print(
        f'posts={len(posts)} rows={stats["rows"]} '
        f'published={stats["published"]} review={stats["review"]} '
        f'skipped={stats["skipped"]}'
    )
    if not args.write:
        return 0

    sqlite_path = args.sqlite
    if sqlite_path is None and not sb.is_configured():
        sqlite_path = Path(TAWJIH_DATABASE)

    if sqlite_path is not None:
        write_sqlite(sqlite_path, rows)
        print(f'wrote sqlite {sqlite_path}')
    if sb.is_configured() and args.sqlite is None:
        upsert_supabase(rows)
        print(f'upserted supabase tawjih ({len(rows)} rows)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
