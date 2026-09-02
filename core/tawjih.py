"""Read path for contemporary توجيه (د. أحمد صابر عبدالهادي).

Not a classical book. Production reads `public.tawjih` via the service_role
key. `data/tawjih.db` is an optional sqlite fallback for tests only.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
from urllib.parse import parse_qs, urlparse

from core.config import TAWJIH_DATABASE
from core.datasets import qpc_hafs_data_normalized
from core.db import connect as _sqlite_connect
from core.memorization import _has_arabic_letter
from core import supabase_editor as sb

logger = logging.getLogger(__name__)

TAWJIH_SOURCE = {
    'name': 'توجيه',
    'title': 'توجيه معاصر',
    'author': 'د. أحمد صابر عبدالهادي',
    'url': 'https://x.com/Dr_ahmed21',
}

_POST_SELECT = 'tweet_id,url,posted_at,media,kind,post_text,reply_text,reply_to_user,reply_to_url'
_ARABIC_TOKEN_RE = re.compile(r'[\u0600-\u06FF]+')

_ARABIC_LETTER_RE = re.compile(r'[\u0600-\u06FF]')
_URL_RE = re.compile(r'https://[^\s<>"\')\]]+', re.IGNORECASE)
_VIDEO_DIM_RE = re.compile(r'/(\d{2,5})x(\d{2,5})(?:/|$)')
_VIDEO_GROUP_RE = re.compile(r'/(?:amplify_video|ext_tw_video|tweet_video)/(\d+)')
_YOUTUBE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')
_TWEET_ID_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_DRIVE_FILE_RE = re.compile(r'/file/d/([^/?#]+)')
_TRAIL_PUNCT = '.,;:!?)»”\'"]'
_PHOTO_CAP = 4
_VIDEO_CAP = 1
_YOUTUBE_CAP = 1
_DRIVE_CAP = 3
_REJECT_HOST_EXACT = {
    't.co', 'www.t.co',
    'chat.whatsapp.com', 'whatsapp.com', 'www.whatsapp.com', 'wa.me', 'api.whatsapp.com',
}
_YOUTUBE_HOSTS = {'youtu.be', 'youtube.com', 'www.youtube.com', 'm.youtube.com'}
_DRIVE_HOSTS = {'drive.google.com', 'www.drive.google.com'}
_X_HOSTS = {'x.com', 'www.x.com', 'twitter.com', 'www.twitter.com'}


def _parse_https(raw: str):
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    scheme = (parsed.scheme or '').lower()
    if scheme != 'https' or not parsed.hostname:
        return None
    return parsed


def _host(parsed) -> str:
    return (parsed.hostname or '').lower()


def _rejected_host(host: str) -> bool:
    if host in _REJECT_HOST_EXACT:
        return True
    if host.endswith('.zoom.us') or host == 'zoom.us':
        return True
    if host.endswith('.whatsapp.com'):
        return True
    if 'acrobat' in host:
        return True
    return False


def _youtube_id(parsed) -> str | None:
    host = _host(parsed)
    path = parsed.path or ''
    parts = [p for p in path.split('/') if p]
    if host == 'youtu.be' and parts:
        candidate = parts[0]
    elif host in _YOUTUBE_HOSTS:
        qs = parse_qs(parsed.query or '')
        if parts and parts[0] == 'watch':
            candidate = (qs.get('v') or [''])[0]
        elif len(parts) >= 2 and parts[0] in {'embed', 'shorts'}:
            candidate = parts[1]
        else:
            return None
    else:
        return None
    candidate = candidate.split('?')[0]
    if _YOUTUBE_ID_RE.fullmatch(candidate):
        return candidate
    return None


def _drive_file_id(parsed) -> str | None:
    host = _host(parsed)
    if host not in _DRIVE_HOSTS:
        return None
    path = parsed.path or ''
    if '/folders/' in path:
        return None
    match = _DRIVE_FILE_RE.search(path)
    if match:
        file_id = match.group(1)
    elif path.rstrip('/').split('/')[-1] == 'open':
        file_id = (parse_qs(parsed.query or '').get('id') or [''])[0]
    else:
        file_id = ''
    if file_id and re.fullmatch(r'[\w-]+', file_id):
        return file_id
    return None


def _collect_urls(*blobs: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for blob in blobs:
        if not blob:
            continue
        for part in str(blob).split(' | '):
            for match in _URL_RE.finditer(part):
                raw = match.group(0).rstrip(_TRAIL_PUNCT)
                if raw and raw not in seen:
                    seen.add(raw)
                    found.append(raw)
    return found


def _primary_text(*blobs: str) -> str:
    for blob in blobs:
        if blob and _ARABIC_LETTER_RE.search(blob):
            return blob
    for blob in blobs:
        if blob and blob.strip():
            return blob
    return ''


def _leftover_media_url(raw: str) -> bool:
    parsed = _parse_https(raw)
    if parsed is None:
        return False
    host = _host(parsed)
    path = (parsed.path or '').lower()
    if path.endswith('.m3u8') or '.m3u8' in path:
        return True
    if host in {'pbs.twimg.com', 'video.twimg.com'}:
        return True
    if host in _YOUTUBE_HOSTS or host == 'www.youtube-nocookie.com':
        return True
    if host in _DRIVE_HOSTS and (
        '/file/' in path or '/folders/' in path or 'id' in parse_qs(parsed.query or '')
    ):
        return True
    if host in _X_HOSTS and '/photo/' in path:
        return True
    return False


def _display_note(primary: str, consumed: set[str]) -> str:
    if not primary:
        return ''

    def _replace(match: re.Match) -> str:
        raw = match.group(0)
        trimmed = raw.rstrip(_TRAIL_PUNCT)
        if trimmed in consumed or _leftover_media_url(trimmed):
            return ' '
        return raw

    cleaned = _URL_RE.sub(_replace, primary)
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r' *\n *', '\n', cleaned)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    return cleaned.strip()


def parse_attachments(*blobs: str, primary: str | None = None) -> tuple[list[dict], str]:
    """Extract allowlisted media URLs and a URL-stripped display note."""
    texts = tuple(str(b) if b is not None else '' for b in blobs)
    videos: dict[str, dict] = {}
    photos: dict[str, dict] = {}
    youtubes: list[dict] = []
    youtube_ids: set[str] = set()
    drives: list[dict] = []
    drive_ids: set[str] = set()
    consumed: set[str] = set()

    for raw in _collect_urls(*texts):
        parsed = _parse_https(raw)
        if parsed is None:
            continue
        host = _host(parsed)
        path = parsed.path or ''
        if _rejected_host(host):
            continue
        if host in _X_HOSTS and '/photo/' in path:
            continue

        if host == 'video.twimg.com' and path.lower().endswith('.mp4'):
            dims = _VIDEO_DIM_RE.search(path)
            width = int(dims.group(1)) if dims else None
            height = int(dims.group(2)) if dims else None
            score = (width or 0) * (height or 0)
            group = _VIDEO_GROUP_RE.search(path)
            key = group.group(1) if group else path
            prev = videos.get(key)
            if prev is None or score > prev['_score']:
                item = {'type': 'video', 'src': raw, '_score': score}
                if width:
                    item['width'] = width
                if height:
                    item['height'] = height
                videos[key] = item
                consumed.add(raw)
            else:
                consumed.add(raw)
            continue

        if host == 'pbs.twimg.com':
            src = raw.replace('name=orig', 'name=small')
            photos.setdefault(path, {'type': 'photo', 'src': src})
            consumed.add(raw)
            continue

        yid = _youtube_id(parsed)
        if yid:
            if yid not in youtube_ids:
                youtube_ids.add(yid)
                youtubes.append({
                    'type': 'youtube',
                    'video_id': yid,
                    'embed': f'https://www.youtube-nocookie.com/embed/{yid}',
                })
            consumed.add(raw)
            continue

        file_id = _drive_file_id(parsed)
        if file_id:
            if file_id not in drive_ids:
                drive_ids.add(file_id)
                drives.append({
                    'type': 'drive',
                    'file_id': file_id,
                    'href': f'https://drive.google.com/file/d/{file_id}/view',
                    'preview': f'https://drive.google.com/file/d/{file_id}/preview',
                    'label': 'ملف على درايف',
                })
            consumed.add(raw)

    ranked = sorted(videos.values(), key=lambda item: item.get('_score', 0), reverse=True)
    video_out = []
    for item in ranked[:_VIDEO_CAP]:
        public = {'type': 'video', 'src': item['src']}
        if 'width' in item:
            public['width'] = item['width']
        if 'height' in item:
            public['height'] = item['height']
        video_out.append(public)

    attachments = (
        video_out
        + youtubes[:_YOUTUBE_CAP]
        + drives[:_DRIVE_CAP]
        + list(photos.values())[:_PHOTO_CAP]
    )
    note_src = str(primary) if primary is not None else _primary_text(*texts)
    return attachments, _display_note(note_src, consumed)



def _safe_tweet_url(raw: str) -> str:
    text = (raw or '').strip()
    parsed = _parse_https(text)
    if parsed is None:
        return ''
    if _host(parsed) in _X_HOSTS:
        return text
    return ''


def _strip_leading_mention(text: str, author: str) -> str:
    body = (text or '').strip()
    handle = (author or '').strip().lstrip('@')
    if not body or not handle:
        return body
    prefix = re.compile(r'^@' + re.escape(handle) + r'(?:\s+|$)', re.IGNORECASE)
    return prefix.sub('', body, count=1).strip()


def _qa_fields(row: dict) -> dict:
    """Question/answer payload for توجيه replies (kind=رد)."""
    empty = {
        'is_reply': False,
        'question': None,
        'question_author': None,
        'question_url': None,
        'answer': None,
    }
    kind = (row.get('kind') or '').strip()
    question = (row.get('post_text') or '').strip()
    reply = (row.get('reply_text') or '').strip()
    note = (row.get('note') or '').strip()
    answer_src = reply or note
    if kind != 'رد' or not question or not answer_src:
        return empty
    author = (row.get('reply_to_user') or '').strip()
    url = _safe_tweet_url(row.get('reply_to_url') or '')
    return {
        'is_reply': True,
        'question': question,
        'question_author': author or None,
        'question_url': url or None,
        'answer': _strip_leading_mention(answer_src, author),
    }


def _entry_attachments(row: dict) -> tuple[list[dict], str]:
    note = row.get('note') or ''
    reply_text = row.get('reply_text') or ''
    primary = None
    if (row.get('kind') or '') == 'رد':
        primary = reply_text or note
    return parse_attachments(
        row.get('media') or '',
        note,
        row.get('post_text') or '',
        reply_text,
        row.get('url') or '',
        primary=primary,
    )




def _rewrite_public_video_attachments(attachments: list[dict], tweet_id: str) -> list[dict]:
    """Point public video src at the same-origin proxy; keep width/height."""
    if not valid_tweet_id(tweet_id):
        return attachments
    out = []
    for att in attachments:
        if att.get('type') != 'video':
            out.append(att)
            continue
        src = att.get('src') or ''
        parsed = _parse_https(src)
        if parsed is None or _host(parsed) != 'video.twimg.com':
            out.append(att)
            continue
        if not (parsed.path or '').lower().endswith('.mp4'):
            out.append(att)
            continue
        public = {'type': 'video', 'src': f'/api/tawjih/media/{tweet_id}'}
        if 'width' in att:
            public['width'] = att['width']
        if 'height' in att:
            public['height'] = att['height']
        out.append(public)
    return out


def _first_twimg_mp4(attachments: list[dict]) -> str | None:
    for att in attachments:
        if att.get('type') != 'video':
            continue
        src = att.get('src') or ''
        parsed = _parse_https(src)
        if parsed is None:
            continue
        path = parsed.path or ''
        if _host(parsed) == 'video.twimg.com' and path.lower().endswith('.mp4'):
            return src
    return None


def valid_tweet_id(tweet_id: str) -> bool:
    return bool(tweet_id) and bool(_TWEET_ID_RE.fullmatch(tweet_id))


def _published_media_row_supabase(tweet_id: str) -> dict | None:
    rows = sb._request(
        'GET',
        'tawjih',
        params={
            'tweet_id': f'eq.{tweet_id}',
            'status': 'eq.published',
            'align_conf': 'eq.1',
            'select': 'tweet_id,note,grade',
            'limit': '1',
        },
    ) or []
    if not rows:
        return None
    row = dict(rows[0])
    posted = sb._request(
        'GET',
        'dr_ahmed21_posts',
        params={
            'tweet_id': f'eq.{tweet_id}',
            'select': _POST_SELECT,
            'limit': '1',
        },
    ) or []
    post = dict(posted[0]) if posted else {}
    row['url'] = post.get('url') or ''
    row['posted_at'] = post.get('posted_at')
    row['media'] = post.get('media') or ''
    row['kind'] = post.get('kind') or ''
    row['post_text'] = post.get('post_text') or ''
    row['reply_text'] = post.get('reply_text') or ''
    row['reply_to_user'] = post.get('reply_to_user') or ''
    row['reply_to_url'] = post.get('reply_to_url') or ''
    return row


def _published_media_row_sqlite(tweet_id: str, db_path: str | None = None) -> dict | None:
    path = db_path or TAWJIH_DATABASE
    if not os.path.exists(path):
        return None
    conn = _sqlite_connect(path, readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT tweet_id, note, grade, url, created_at '
            'FROM tawjih WHERE tweet_id=? AND status=? AND align_conf=1 '
            'LIMIT 1',
            (tweet_id, 'published'),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def published_video_url(tweet_id: str) -> str | None:
    """First allowlisted video.twimg.com .mp4 on a published, aligned tweet.

    Any verse is fine — one video per tweet. Returns None for unknown,
    unpublished, unaligned, or non-twimg sources. Never an open proxy.
    """
    if not valid_tweet_id(tweet_id):
        return None
    try:
        if sb.is_configured():
            row = _published_media_row_supabase(tweet_id)
        else:
            row = _published_media_row_sqlite(tweet_id)
    except Exception:
        logger.exception('tawjih media lookup failed for %s', tweet_id)
        return None
    if not row:
        return None
    attachments, _display = _entry_attachments(row)
    return _first_twimg_mp4(attachments)


def verse_is_valid(surah: int, ayah: int) -> bool:
    if not (1 <= surah <= 114) or ayah < 1:
        return False
    return f'{surah}:{ayah}' in qpc_hafs_data_normalized


def verse_words(surah: int, ayah: int) -> list[str]:
    """Recited-word list (ornaments dropped), same basis as `_verse_word_texts`."""
    td = qpc_hafs_data_normalized.get(f'{surah}:{ayah}')
    text = (td.get('text', '') if isinstance(td, dict) else '') or ''
    return [tok for tok in text.split() if _has_arabic_letter(tok)]


def _stop_word(surah: int, ayah: int, wpos: int) -> str:
    words = verse_words(surah, ayah)
    if 0 <= wpos < len(words):
        return words[wpos]
    return ''


def quote_span(surah: int, ayah: int, wpos: int, quote: str | None) -> tuple[int, int]:
    """Inclusive word range of the quoted span ending at ``wpos``.

    Alignment stores the stop word (last quoted token). Recover the start
    from the quote's Arabic token count, clamped to the verse.
    """
    words = verse_words(surah, ayah)
    if not words or wpos < 0 or wpos >= len(words):
        return max(0, wpos), max(0, wpos)
    tokens = _ARABIC_TOKEN_RE.findall(quote or '')
    width = len(tokens) or 1
    start = max(0, wpos - width + 1)
    return start, wpos


def _shape_entry(row: dict, surah: int, ayah: int) -> dict | None:
    try:
        wpos = int(row['wpos'])
    except (TypeError, ValueError, KeyError):
        return None
    stop_word = _stop_word(surah, ayah, wpos)
    if not stop_word:
        return None
    created = row.get('created_at') or row.get('posted_at') or None
    quote = row.get('quote') or ''
    start, end = quote_span(surah, ayah, wpos, quote)
    words = verse_words(surah, ayah)
    attachments, display_note = _entry_attachments(row)
    tweet_id = str(row.get('tweet_id') or '')
    attachments = _rewrite_public_video_attachments(attachments, tweet_id)
    shaped = {
        'tweet_id': tweet_id,
        'wpos': end,
        'wpos_start': start,
        'stop_word': stop_word,
        'phrase': words[start:end + 1],
        'quote': quote,
        'note': row.get('note') or '',
        'grade': row.get('grade') or None,
        'url': row.get('url') or '',
        'created_at': created,
        'attachments': attachments,
        'display_note': display_note,
    }
    shaped.update(_qa_fields(row))
    return shaped


def _from_supabase(surah: int, ayah: int) -> list[dict]:
    rows = sb._request(
        'GET',
        'tawjih',
        params={
            'surah': f'eq.{surah}',
            'ayah': f'eq.{ayah}',
            'status': 'eq.published',
            'align_conf': 'eq.1',
            'select': 'tweet_id,wpos,quote,note,grade',
            'order': 'wpos.asc',
        },
    ) or []
    tweet_ids = sorted({str(r.get('tweet_id') or '') for r in rows if r.get('tweet_id')})
    posts = {}
    if tweet_ids:
        posted = sb._request(
            'GET',
            'dr_ahmed21_posts',
            params={
                'tweet_id': 'in.(' + ','.join(f'"{tid}"' for tid in tweet_ids) + ')',
                'select': _POST_SELECT,
            },
        ) or []
        posts = {str(p['tweet_id']): p for p in posted if p.get('tweet_id')}
    out = []
    for row in rows:
        post = posts.get(str(row.get('tweet_id') or ''), {})
        merged = dict(row)
        merged['url'] = post.get('url') or ''
        merged['posted_at'] = post.get('posted_at')
        merged['media'] = post.get('media') or ''
        merged['kind'] = post.get('kind') or ''
        merged['post_text'] = post.get('post_text') or ''
        merged['reply_text'] = post.get('reply_text') or ''
        merged['reply_to_user'] = post.get('reply_to_user') or ''
        merged['reply_to_url'] = post.get('reply_to_url') or ''
        shaped = _shape_entry(merged, surah, ayah)
        if shaped:
            out.append(shaped)
    return out


def _from_sqlite(surah: int, ayah: int, db_path: str | None = None) -> list[dict]:
    path = db_path or TAWJIH_DATABASE
    if not os.path.exists(path):
        return []
    conn = _sqlite_connect(path, readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            'SELECT tweet_id, wpos, quote, note, grade, url, created_at '
            'FROM tawjih WHERE surah=? AND ayah=? AND status=? AND align_conf=1 '
            'ORDER BY wpos',
            (surah, ayah, 'published'),
        ).fetchall()
        out = []
        for row in rows:
            shaped = _shape_entry(dict(row), surah, ayah)
            if shaped:
                out.append(shaped)
        return out
    finally:
        conn.close()


def list_published(surah: int, ayah: int) -> list[dict]:
    """Published, uniquely-aligned توجيه for one verse.

    Supabase is the production store. Sqlite is used only when Supabase is
    not configured (tests / offline). A configured-but-empty cloud table is
    a real empty result, not a cue to mix in local rows.
    """
    if sb.is_configured():
        try:
            return _from_supabase(surah, ayah)
        except Exception:
            logger.exception('tawjih supabase read failed for %s:%s', surah, ayah)
            return []
    return _from_sqlite(surah, ayah)


def ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS tawjih (
            id INTEGER PRIMARY KEY,
            tweet_id TEXT NOT NULL,
            surah INTEGER,
            ayah INTEGER,
            wpos INTEGER,
            quote TEXT,
            note TEXT NOT NULL DEFAULT '',
            grade TEXT,
            status TEXT NOT NULL CHECK (status IN ('published','review','skipped')),
            align_conf INTEGER NOT NULL DEFAULT 0,
            skip_reason TEXT,
            locator TEXT,
            url TEXT,
            created_at TEXT
        )'''
    )
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS tawjih_span_uidx '
        'ON tawjih (tweet_id, surah, ayah, wpos)'
    )


REVIEW_GRADES = ('تام', 'كاف', 'حسن', 'جائز', 'قبيح', 'لازم', 'لا يوقف')
_REVIEW_STATUSES = ('published', 'review', 'skipped')
_ITEM_SELECT = (
    'id,tweet_id,status,surah,ayah,wpos,quote,note,grade,'
    'align_conf,skip_reason,locator'
)
_REVIEW_POST_SELECT = 'tweet_id,kind,post_text,reply_text,reply_to_user,reply_to_url,url,posted_at,media'


class TawjihReviewError(Exception):
    """HTTP-mappable review error (status is 400, 404, or 409)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _as_int(value):
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_verse_words(surah: int, ayah: int) -> tuple[list[str] | None, str | None]:
    """Return (words, None) or (None, 'invalid'|'missing')."""
    if not (1 <= surah <= 114) or ayah < 1:
        return None, 'invalid'
    if not verse_is_valid(surah, ayah):
        return None, 'missing'
    words = verse_words(surah, ayah)
    if not words:
        return None, 'missing'
    return words, None


def _tweet_body(kind: str, post_text: str, reply_text: str, note: str) -> str:
    if kind == 'رد':
        body = (reply_text or '').strip()
    else:
        body = (post_text or '').strip()
    return body or (note or '')


def _shape_review_item(row: dict, post: dict | None = None) -> dict:
    post = post or {}
    surah = _as_int(row.get('surah'))
    ayah = _as_int(row.get('ayah'))
    wpos = _as_int(row.get('wpos'))
    kind = post.get('kind') or ''
    post_text = post.get('post_text') or ''
    reply_text = post.get('reply_text') or ''
    note = row.get('note') or ''
    words: list[str] = []
    if surah is not None and ayah is not None and verse_is_valid(surah, ayah):
        words = verse_words(surah, ayah)
    align = _as_int(row.get('align_conf'))
    primary = (reply_text or note) if kind == 'رد' else None
    attachments, display_note = parse_attachments(
        post.get('media') or row.get('media') or '',
        note,
        post_text,
        reply_text,
        post.get('url') or row.get('url') or '',
        primary=primary,
    )
    qa = _qa_fields({
        'kind': kind,
        'post_text': post_text,
        'reply_text': reply_text,
        'note': note,
        'reply_to_user': post.get('reply_to_user') or row.get('reply_to_user') or '',
        'reply_to_url': post.get('reply_to_url') or row.get('reply_to_url') or '',
    })
    return {
        'id': _as_int(row.get('id')),
        'tweet_id': str(row.get('tweet_id') or ''),
        'status': row.get('status') or '',
        'surah': surah,
        'ayah': ayah,
        'wpos': wpos,
        'quote': row.get('quote') or '',
        'note': note,
        'grade': row.get('grade') or None,
        'align_conf': 0 if align is None else align,
        'skip_reason': row.get('skip_reason'),
        'locator': row.get('locator') or '',
        'url': post.get('url') or row.get('url') or '',
        'kind': kind,
        'post_text': post_text,
        'reply_text': reply_text,
        'posted_at': post.get('posted_at') or row.get('created_at'),
        'tweet_body': _tweet_body(kind, post_text, reply_text, note),
        'verse_words': words,
        'attachments': attachments,
        'display_note': display_note,
        **qa,
    }


def _join_posts(rows: list[dict]) -> dict[str, dict]:
    tweet_ids = sorted({str(r.get('tweet_id') or '') for r in rows if r.get('tweet_id')})
    if not tweet_ids:
        return {}
    posted = sb._request(
        'GET',
        'dr_ahmed21_posts',
        params={
            'tweet_id': 'in.(' + ','.join(f'"{tid}"' for tid in tweet_ids) + ')',
            'select': _REVIEW_POST_SELECT,
        },
    ) or []
    return {str(p['tweet_id']): p for p in posted if p.get('tweet_id')}


def _empty_counts() -> dict:
    return {'published': 0, 'review': 0, 'skipped': 0}


def _with_total(counts: dict) -> dict:
    return {
        'published': counts['published'],
        'review': counts['review'],
        'skipped': counts['skipped'],
        'total': counts['published'] + counts['review'] + counts['skipped'],
        'source': TAWJIH_SOURCE,
    }


def _summary_supabase() -> dict:
    counts = _empty_counts()
    rows = sb._request('GET', 'tawjih', params={'select': 'status'}) or []
    for row in rows:
        status = row.get('status')
        if status in counts:
            counts[status] += 1
    return _with_total(counts)


def _summary_sqlite(db_path: str | None) -> dict:
    counts = _empty_counts()
    path = db_path or TAWJIH_DATABASE
    if not os.path.exists(path):
        return _with_total(counts)
    conn = _sqlite_connect(path, readonly=True)
    try:
        for status, n in conn.execute('SELECT status, COUNT(*) FROM tawjih GROUP BY status'):
            if status in counts:
                counts[status] = int(n)
    finally:
        conn.close()
    return _with_total(counts)


def review_summary(db_path: str | None = None) -> dict:
    """Counts of tawjih rows by status, plus TAWJIH_SOURCE meta."""
    if sb.is_configured():
        return _summary_supabase()
    return _summary_sqlite(db_path)


def _paginate(total: int, page: int, limit: int) -> tuple[int, int, int]:
    page = max(1, int(page))
    limit = min(50, max(1, int(limit)))
    pages = max(1, (total + limit - 1) // limit) if total else 1
    return page, limit, pages


def _items_supabase(status: str, page: int, limit: int) -> dict:
    count_params: dict[str, str] = {'select': 'id', 'order': 'id.asc'}
    page_params: dict[str, str] = {
        'select': _ITEM_SELECT,
        'order': 'id.asc',
        'offset': str((page - 1) * limit),
        'limit': str(limit),
    }
    if status != 'all':
        count_params['status'] = f'eq.{status}'
        page_params['status'] = f'eq.{status}'
    ids = sb._request('GET', 'tawjih', params=count_params) or []
    total = len(ids)
    page, limit, pages = _paginate(total, page, limit)
    page_params['offset'] = str((page - 1) * limit)
    page_params['limit'] = str(limit)
    rows = sb._request('GET', 'tawjih', params=page_params) or []
    posts = _join_posts(rows)
    items = [
        _shape_review_item(dict(row), posts.get(str(row.get('tweet_id') or ''), {}))
        for row in rows
    ]
    return {'items': items, 'total': total, 'page': page, 'limit': limit, 'pages': pages}


def _items_sqlite(status: str, page: int, limit: int, db_path: str | None) -> dict:
    path = db_path or TAWJIH_DATABASE
    if not os.path.exists(path):
        page, limit, pages = _paginate(0, page, limit)
        return {'items': [], 'total': 0, 'page': page, 'limit': limit, 'pages': pages}
    where = ''
    params: list = []
    if status != 'all':
        where = ' WHERE status=?'
        params.append(status)
    conn = _sqlite_connect(path, readonly=True)
    try:
        conn.row_factory = sqlite3.Row
        total = conn.execute(
            'SELECT COUNT(*) FROM tawjih' + where, params
        ).fetchone()[0]
        page, limit, pages = _paginate(int(total), page, limit)
        rows = conn.execute(
            'SELECT id, tweet_id, status, surah, ayah, wpos, quote, note, grade, '
            'align_conf, skip_reason, locator, url, created_at '
            'FROM tawjih' + where + ' ORDER BY id ASC LIMIT ? OFFSET ?',
            [*params, limit, (page - 1) * limit],
        ).fetchall()
        items = [_shape_review_item(dict(row)) for row in rows]
    finally:
        conn.close()
    return {'items': items, 'total': int(total), 'page': page, 'limit': limit, 'pages': pages}


def list_review_items(
    status: str,
    page: int,
    limit: int,
    db_path: str | None = None,
) -> dict:
    """Paginated tawjih rows for the editor review UI."""
    page, limit, _ = _paginate(0, page, limit)
    if sb.is_configured():
        return _items_supabase(status, page, limit)
    return _items_sqlite(status, page, limit, db_path)


def _patch_supabase(row_id: int, fields: dict) -> dict:
    rows = sb._request(
        'PATCH',
        'tawjih',
        params={'id': f'eq.{row_id}'},
        json_body=fields,
        prefer='return=representation',
    ) or []
    if not rows:
        raise TawjihReviewError(404, 'review row not found')
    return dict(rows[0])


def _patch_sqlite(row_id: int, fields: dict, db_path: str | None) -> dict:
    path = db_path or TAWJIH_DATABASE
    if not os.path.exists(path):
        raise TawjihReviewError(404, 'review row not found')
    assignments = ', '.join(f'{col}=?' for col in fields)
    values = list(fields.values())
    conn = _sqlite_connect(path)
    try:
        ensure_sqlite_schema(conn)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            f'UPDATE tawjih SET {assignments} WHERE id=?',
            [*values, row_id],
        )
        if cur.rowcount == 0:
            raise TawjihReviewError(404, 'review row not found')
        conn.commit()
        row = conn.execute('SELECT * FROM tawjih WHERE id=?', (row_id,)).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def apply_review_decision(
    row_id: int,
    decision: str,
    *,
    surah=None,
    ayah=None,
    wpos=None,
    quote=None,
    grade=None,
    db_path: str | None = None,
) -> dict:
    """Publish (add) or skip (discard) one tawjih row. Raises TawjihReviewError."""
    if decision not in {'add', 'discard'}:
        raise TawjihReviewError(400, 'invalid decision')
    if decision == 'add':
        try:
            surah_i = int(surah)
            ayah_i = int(ayah)
            wpos_i = int(wpos)
        except (TypeError, ValueError):
            raise TawjihReviewError(
                409, 'add requires a verified surah, ayah, and word position'
            ) from None
        words, err = get_verse_words(surah_i, ayah_i)
        if err == 'invalid' or err == 'missing' or not words:
            raise TawjihReviewError(409, 'invalid verse')
        if not (0 <= wpos_i < len(words)):
            raise TawjihReviewError(409, 'invalid word position')
        quote_text = (quote or '').strip() or words[wpos_i]
        fields = {
            'status': 'published',
            'align_conf': 1,
            'surah': surah_i,
            'ayah': ayah_i,
            'wpos': wpos_i,
            'quote': quote_text,
            'skip_reason': None,
        }
        if grade not in (None, ''):
            grade_text = str(grade).strip()
            if grade_text not in REVIEW_GRADES:
                raise TawjihReviewError(400, 'invalid waqf grade')
            fields['grade'] = grade_text
    else:
        fields = {
            'status': 'skipped',
            'skip_reason': 'reviewer_discard',
        }
    if sb.is_configured():
        updated = _patch_supabase(row_id, fields)
    else:
        updated = _patch_sqlite(row_id, fields, db_path)
    return {
        'ok': True,
        'id': _as_int(updated.get('id')) or row_id,
        'decision': decision,
        'status': updated.get('status'),
        'surah': _as_int(updated.get('surah')),
        'ayah': _as_int(updated.get('ayah')),
        'wpos': _as_int(updated.get('wpos')),
        'quote': updated.get('quote') or '',
    }

