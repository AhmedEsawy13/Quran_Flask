"""Media-aware توجيه attachments: X video, Drive, YouTube, photos."""
from __future__ import annotations

from core.tawjih import parse_attachments


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

