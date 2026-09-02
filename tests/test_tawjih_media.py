"""Media-aware توجيه attachments: X video, Drive, YouTube, photos."""
from __future__ import annotations

from core.tawjih import parse_attachments, published_video_url, valid_tweet_id
from tests.test_tawjih import (
    UNIQUE_AYAH,
    UNIQUE_SURAH,
    _published_fixture,
    _write_fixture,
)


LOW_MP4 = 'https://video.twimg.com/amplify_video/1512897902158434312/vid/avc1/360x640/low.mp4'
HIGH_MP4 = 'https://video.twimg.com/amplify_video/1512897902158434312/vid/avc1/720x1280/high.mp4'
M3U8 = 'https://video.twimg.com/amplify_video/1512897902158434312/pl/stream.m3u8'
DRIVE_FILE = 'https://drive.google.com/file/d/1AbCDefGhIJKlmnoPQRstuVWX/view?usp=sharing'
DRIVE_OPEN = 'https://drive.google.com/open?id=1AbCDefGhIJKlmnoPQRstuVWX'
DRIVE_FOLDER = 'https://drive.google.com/drive/folders/1FolderIdNotAFile'
YOUTUBE = 'https://youtu.be/dQw4w9WgXcQ'
WHATSAPP = 'https://chat.whatsapp.com/inviteABC'
ZOOM = 'https://us06web.zoom.us/j/123456789'
PHOTO_ORIG = 'https://pbs.twimg.com/media/Fexample?format=jpg&name=orig'
X_PHOTO = 'https://x.com/Dr_ahmed21/status/1512897902158434312/photo/1'


def test_best_mp4_wins_and_m3u8_is_ignored():
    media = f'{LOW_MP4} | {M3U8} | {HIGH_MP4}'
    attachments, _note = parse_attachments(media)
    assert len(attachments) == 1
    video = attachments[0]
    assert video['type'] == 'video'
    assert video['src'] == HIGH_MP4
    assert video['width'] == 720
    assert video['height'] == 1280
    assert all('.m3u8' not in (a.get('src') or '') for a in attachments)


def test_drive_file_becomes_preview_and_folders_are_ignored():
    attachments, _note = parse_attachments(
        f'ملف {DRIVE_FILE} ومجلد {DRIVE_FOLDER}'
    )
    assert len(attachments) == 1
    drive = attachments[0]
    assert drive == {
        'type': 'drive',
        'file_id': '1AbCDefGhIJKlmnoPQRstuVWX',
        'href': 'https://drive.google.com/file/d/1AbCDefGhIJKlmnoPQRstuVWX/view',
        'preview': 'https://drive.google.com/file/d/1AbCDefGhIJKlmnoPQRstuVWX/preview',
        'label': 'ملف على درايف',
    }
    opened, _ = parse_attachments(DRIVE_OPEN)
    assert opened[0]['file_id'] == '1AbCDefGhIJKlmnoPQRstuVWX'


def test_youtube_youtu_be_id():
    attachments, _note = parse_attachments(YOUTUBE)
    assert attachments == [{
        'type': 'youtube',
        'video_id': 'dQw4w9WgXcQ',
        'embed': 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ',
    }]


def test_rejects_whatsapp_and_zoom():
    attachments, note = parse_attachments(
        f'لقاء {ZOOM} وعلى واتساب {WHATSAPP}'
    )
    assert attachments == []
    assert 'zoom' in note.lower() or 'واتساب' in note


def test_display_note_strips_consumed_urls_and_keeps_arabic():
    blob = (
        'الوقف هنا على جهني.\n\n'
        f'{HIGH_MP4}\n'
        f'{M3U8}\n'
        f'{X_PHOTO}\n'
        f'{PHOTO_ORIG}\n'
        'وهذا توجيه معاصر.'
    )
    attachments, display_note = parse_attachments(blob)
    types = [a['type'] for a in attachments]
    assert 'video' in types
    assert 'photo' in types
    assert HIGH_MP4 not in display_note
    assert M3U8 not in display_note
    assert 'pbs.twimg.com' not in display_note
    assert '/photo/' not in display_note
    assert 'الوقف هنا على جهني.' in display_note
    assert 'وهذا توجيه معاصر.' in display_note


def test_photo_orig_rewritten_to_small():
    attachments, _ = parse_attachments(PHOTO_ORIG)
    assert attachments == [{
        'type': 'photo',
        'src': 'https://pbs.twimg.com/media/Fexample?format=jpg&name=small',
    }]


def test_attachment_order_is_video_youtube_drive_photo():
    blob = f'{PHOTO_ORIG} {DRIVE_FILE} {YOUTUBE} {HIGH_MP4}'
    attachments, _ = parse_attachments(blob)
    assert [a['type'] for a in attachments] == ['video', 'youtube', 'drive', 'photo']

def test_primary_reply_keeps_display_note_when_question_is_longer():
    question = 'ما حكم الوقف على قوله تعالى في هذه الآية الكريمة أيها الشيخ الفاضل بارك الله فيكم؟'
    reply = 'الوقف هنا تام.'
    attachments, display_note = parse_attachments(
        HIGH_MP4, question, reply, primary=reply,
    )
    assert display_note == reply
    assert question not in display_note
    assert attachments and attachments[0]['type'] == 'video'
    # Without primary, the longer Arabic question would win as display_note.
    _, fallback = parse_attachments(HIGH_MP4, question, reply)
    assert question in fallback

def _sqlite_media_db(tmp_path, monkeypatch, rows):
    db = tmp_path / 'tawjih.db'
    _write_fixture(db, rows)
    monkeypatch.setattr('core.tawjih.TAWJIH_DATABASE', str(db))
    monkeypatch.setattr('core.tawjih.sb.is_configured', lambda: False)
    return db


def test_valid_tweet_id_accepts_snowflake_and_fixtures():
    assert valid_tweet_id('1917669728031760535')
    assert valid_tweet_id('fixture-published')
    assert valid_tweet_id('1001')
    assert not valid_tweet_id('')
    assert not valid_tweet_id('foo.bar')
    assert not valid_tweet_id('id with space')


def test_api_rewrites_video_src_to_same_origin_proxy(client, tmp_path, monkeypatch):
    fixture = _published_fixture(note=f'الوقف هنا تام.\n{HIGH_MP4}')
    _sqlite_media_db(tmp_path, monkeypatch, [fixture])
    payload = client.get(f'/api/tawjih/{UNIQUE_SURAH}/{UNIQUE_AYAH}').get_json()
    assert payload['count'] == 1
    att = payload['entries'][0]['attachments'][0]
    assert att['type'] == 'video'
    assert att['src'] == f'/api/tawjih/media/{fixture["tweet_id"]}'
    assert HIGH_MP4 not in att['src']
    assert att['width'] == 720
    assert att['height'] == 1280
    raw, _ = parse_attachments(HIGH_MP4)
    assert raw[0]['src'] == HIGH_MP4


def test_media_unknown_tweet_is_404(client, tmp_path, monkeypatch):
    _sqlite_media_db(tmp_path, monkeypatch, [_published_fixture()])
    response = client.get('/api/tawjih/media/not-real')
    assert response.status_code == 404


def test_media_empty_path_is_404_or_400(client):
    assert client.get('/api/tawjih/media/').status_code in {400, 404}


def test_media_invalid_tweet_id_is_400(client):
    assert client.get('/api/tawjih/media/foo.bar').status_code == 400


def test_published_video_url_none_for_review_or_low_conf(tmp_path, monkeypatch):
    review = _published_fixture(
        tweet_id='fixture-review', status='review', align_conf=0, note=HIGH_MP4,
    )
    low = _published_fixture(
        tweet_id='fixture-lowconf', align_conf=0, status='published', note=HIGH_MP4,
    )
    _sqlite_media_db(tmp_path, monkeypatch, [review, low])
    assert published_video_url('fixture-review') is None
    assert published_video_url('fixture-lowconf') is None
    assert published_video_url('not-real') is None


def test_media_proxy_forwards_range_and_body(client, tmp_path, monkeypatch):
    fixture = _published_fixture(note=HIGH_MP4)
    _sqlite_media_db(tmp_path, monkeypatch, [fixture])
    captured = {}

    class FakeResp:
        status_code = 206
        headers = {
            'Content-Type': 'video/mp4',
            'Content-Length': '2',
            'Content-Range': 'bytes 0-1/99',
            'Accept-Ranges': 'bytes',
        }
        url = HIGH_MP4

        def iter_content(self, chunk_size=64 * 1024):
            yield b'AB'

        def close(self):
            pass

    def fake_get(url, **kwargs):
        captured['url'] = url
        captured['headers'] = kwargs.get('headers') or {}
        captured['stream'] = kwargs.get('stream')
        captured['timeout'] = kwargs.get('timeout')
        return FakeResp()

    monkeypatch.setattr('modules.breathing.requests.get', fake_get)
    response = client.get(
        f'/api/tawjih/media/{fixture["tweet_id"]}',
        headers={'Range': 'bytes=0-1'},
    )
    assert captured['url'] == HIGH_MP4
    assert captured['stream'] is True
    assert captured['headers'].get('Range') == 'bytes=0-1'
    assert 'athar-web-teal.vercel.app' not in (captured['headers'].get('Referer') or '')
    assert response.status_code in {200, 206}
    assert (response.content_type or '').startswith('video/mp4')
    assert response.data == b'AB'
    assert response.headers.get('Content-Range') == 'bytes 0-1/99'
    cache = response.headers.get('Cache-Control', '')
    assert 'max-age=86400' in cache
    assert 'no-store' not in cache
