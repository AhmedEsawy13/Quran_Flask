"""Mesaha printed-line seating from Kraken wide-line geometry.

These fixtures do not need mushaf DBs or Ahmed's 826 Kraken JSON files.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.mesaha_printed_seating import (
    COLLAPSE_WORDS,
    EMPTY_TOP_Y_JPEG,
    JPEG_TEXT_BOTTOM,
    JPEG_TEXT_TOP,
    LINE_Y_MERGE,
    KrakenLine,
    clip_empty_top_page_starts,
    geometry_from_wide_specs,
    kraken_lines_from_payload,
    load_kraken_geometries,
    merge_kraken_lines,
    normalize_letters,
    page_text_geometry,
    seat_printed_page,
    slot_for_y,
)


@dataclass(frozen=True)
class W:
    index: int
    surah: int
    ayah: int
    text: str
    normalized: str
    word_key: str = ''


def _words(lines: list[str], *, surah: int, start_index: int = 1, start_ayah: int = 1) -> list[W]:
    out: list[W] = []
    index = start_index
    ayah = start_ayah
    for line in lines:
        position = 0
        for text in line.split():
            position += 1
            out.append(W(
                index=index,
                surah=surah,
                ayah=ayah,
                text=text,
                normalized=normalize_letters(text),
                word_key=f'{surah}:{ayah}:{position}',
            ))
            index += 1
        ayah += 1
    return out


def _wide(y: int, text: str) -> tuple[int, str, int, int]:
    return (y, text, 80, 1980)


def _ayah_rows(seating) -> list:
    return [
        line for line in seating.lines
        if line.line_type == 'ayah' and line.start_pos is not None
    ]


def _line_text(words: list[W], line) -> str:
    return ' '.join(word.text for word in words[line.start_pos:line.end_pos + 1])


HIGH_BODY_LINES = [
    'وراء ظهورهم واشتروا به ثمنا قليلا',
    'الشياطين على ملك سليمان وما كفر سليمان',
    'الشياطين كفروا يعلمون الناس السحر وما انزل',
    'الملكين ببابل هاروت وماروت وما يعلمان من أحد',
    'حتى يقولا إنما نحن فتنة فلا تكفر فيتعلمون منهما',
    'ما يفرقون به بين المرء وزوجه وما هم بضارين به',
    'من أحد إلا بإذن الله ويتعلمون ما يضرهم ولا ينفعهم',
    'ولقد علموا لمن اشتراه ما له في الآخرة من خلاق ولبئس',
    'ما شروا به أنفسهم لو كانوا يعلمون ولو أنهم آمنوا',
    'واتقوا لمثوبة من عند الله خير لو كانوا يعلمون',
    'يا أيها الذين آمنوا لا تقولوا راعنا وقولوا انظرنا واسمعوا',
    'وللكافرين عذاب أليم ما يود الذين كفروا من',
]
HIGH_BODY_YS = [612, 760, 908, 1056, 1204, 1352, 1500, 1648, 1796, 1944, 2092, 2240]


def test_line_y_merge_constant_is_ahmeds_162():
    assert LINE_Y_MERGE == 162
    assert EMPTY_TOP_Y_JPEG == 1100
    assert COLLAPSE_WORDS == 20


def test_slot_for_y_uses_per_page_jpeg_band():
    assert slot_for_y(612, 12, JPEG_TEXT_TOP, JPEG_TEXT_BOTTOM) == 1
    assert slot_for_y(1312, 12, JPEG_TEXT_TOP, JPEG_TEXT_BOTTOM) == 5
    assert slot_for_y(2240, 12, JPEG_TEXT_TOP, JPEG_TEXT_BOTTOM) == 11


def test_consecutive_full_ayah_lines_are_not_merged_at_line_y_merge():
    first = KrakenLine(
        y=612, x0=80, x1=1980,
        text=HIGH_BODY_LINES[0],
        normalized=normalize_letters(HIGH_BODY_LINES[0]),
        n_tokens=len(HIGH_BODY_LINES[0].split()),
    )
    second = KrakenLine(
        y=760, x0=80, x1=1980,
        text=HIGH_BODY_LINES[1],
        normalized=normalize_letters(HIGH_BODY_LINES[1]),
        n_tokens=len(HIGH_BODY_LINES[1].split()),
    )
    assert abs(second.y - first.y) < LINE_Y_MERGE
    merged = merge_kraken_lines([first, second])
    assert len(merged) == 2


def test_narrow_fragment_within_line_y_merge_joins_the_ayah_line():
    body = KrakenLine(
        y=612, x0=80, x1=1980,
        text=HIGH_BODY_LINES[0],
        normalized=normalize_letters(HIGH_BODY_LINES[0]),
        n_tokens=len(HIGH_BODY_LINES[0].split()),
    )
    marks = KrakenLine(
        y=700, x0=400, x1=700,
        text='َ',
        normalized='',
        n_tokens=1,
    )
    merged = merge_kraken_lines([body, marks])
    assert len(merged) == 1
    assert merged[0].width >= 900


def test_mid_page_banner_with_ink_at_y600_is_not_empty_top():
    prev_lines = [
        'تلك الرسل فضلنا بعضهم على بعض',
        'منهم من كلم الله ورفع بعضهم درجات',
        'وآتينا عيسى ابن مريم البينات',
        'وأيدناه بروح القدس ولو شاء الله',
        'ما اقتتل الذين من بعدهم من بعد',
    ]
    new_lines = [
        'يا أيها الناس اتقوا ربكم الذي خلقكم من نفس',
        'واحدة وخلق منها زوجها وبث منهما رجالا',
        'كثيرا ونساء واتقوا الله الذي تساءلون به',
        'والأرحام إن الله كان عليكم رقيبا',
    ]
    ys = [620, 770, 920, 1070, 1220, 1600, 1750, 1900, 2050]
    geometry = geometry_from_wide_specs(
        [_wide(y, text) for y, text in zip(ys, prev_lines + new_lines)],
        banner_text='سورة النساء مدنية',
        banner_y=1400,
        basmala_text='بسم الله الرحمن الرحيم',
        basmala_y=1480,
    )
    assert geometry.has_banner is True
    assert geometry.first_wide_y == 620
    assert geometry.is_empty_top is False
    assert geometry.n_wide == 9

    previous = _words(prev_lines, surah=3, start_index=100, start_ayah=190)
    following = _words(new_lines, surah=4, start_index=200, start_ayah=1)
    words = previous + following
    # Surah 3 started on an earlier page; only النساء begins here.
    starts_by_surah = {3: -1, 4: len(previous)}
    page_starts = [0, 0, len(words)]
    clip_empty_top_page_starts(
        page_starts, words, {97: geometry}, starts_by_surah, page_min=96,
    )
    # Must keep الرعد / previous-surah ink; do not treat y~600 as empty-top.
    assert page_starts[1] < len(previous)

    seating = seat_printed_page(
        words=words,
        page_start=0,
        page_end=len(words) - 1,
        starts_by_surah=starts_by_surah,
        geometry=geometry,
        target_lines=12,
    )
    assert seating is not None
    ayahs = _ayah_rows(seating)
    assert ayahs[0].surah == 3
    assert words[ayahs[0].start_pos].text == 'تلك'
    header_slots = [line.line_number for line in seating.lines if line.line_type != 'ayah']
    assert header_slots == [6, 7, 8]
    new_first = next(line for line in ayahs if line.surah == 4)
    assert words[new_first.start_pos].text == 'يا'
    assert new_first.line_number == 9


def test_empty_top_banner_page_does_not_seat_previous_surah_or_collapse():
    leftover = _words(
        ['فأما الذين كفروا فأعذبهم عذابا شديدا'],
        surah=3, start_index=50, start_ayah=199,
    )
    body_lines = [
        'يا أيها الناس اتقوا ربكم الذي خلقكم من نفس',
        'واحدة وخلق منها زوجها وبث منهما رجالا كثيرا ونساء',
        'واتقوا الله الذي تساءلون به والأرحام إن الله كان',
        'عليكم رقيبا يا أيها الذين آمنوا لا تأكلوا أموالكم',
        'بينكم بالباطل إلا أن تكون تجارة عن تراض منكم',
        'ولا تقتلوا أنفسكم إن الله كان بكم رحيما ومن يفعل',
        'ذلك عدوانا وظلما فسوف نصليه نارا وكان ذلك على الله',
        'يسيرا وإن خفتم ألا تقسطوا في اليتامى فانكحوا ما طاب',
    ]
    body = _words(body_lines, surah=4, start_index=80, start_ayah=1)
    words = leftover + body
    starts_by_surah = {3: -1, 4: len(leftover)}
    ys = [1312 + i * 150 for i in range(8)]
    geometry = geometry_from_wide_specs(
        [_wide(y, text) for y, text in zip(ys, body_lines)],
        banner_text='سورة النساء مدنية',
        banner_y=420,
        basmala_text='بسم الله الرحمن الرحيم',
        basmala_y=1180,
    )
    assert geometry.is_empty_top is True
    assert geometry.n_wide == 8
    assert geometry.first_wide_y >= 1100

    starts = [0, 0, len(words)]
    clip_empty_top_page_starts(
        starts, words, {97: geometry}, starts_by_surah, page_min=96,
    )
    assert starts[1] == len(leftover)

    seating = seat_printed_page(
        words=words,
        page_start=starts[1],
        page_end=len(words) - 1,
        starts_by_surah=starts_by_surah,
        geometry=geometry,
        target_lines=12,
    )
    assert seating is not None
    ayahs = _ayah_rows(seating)
    assert all(line.surah == 4 for line in ayahs)
    assert words[ayahs[0].start_pos].text == 'يا'
    assert max(line.end_pos - line.start_pos + 1 for line in ayahs) < COLLAPSE_WORDS
    assert ayahs[0].line_number >= 5
    header_types = [
        line.line_type for line in seating.lines
        if line.line_type != 'ayah'
    ]
    assert header_types == ['surah_name', 'surah_info', 'basmallah']
    assert all(line.line_number <= 3 for line in seating.lines if line.line_type != 'ayah')
    # Banner/basmala occupy the printed top; leftover Al-Imran is not in L1–L3.
    top = [line for line in seating.lines if line.line_number <= 3]
    assert not any(
        line.start_pos is not None and words[line.start_pos].surah == 3
        for line in top
    )


def test_high_body_wrap_uses_next_kraken_line_start_not_token_count():
    words = _words(HIGH_BODY_LINES, surah=2, start_index=400, start_ayah=101)
    # Simulate an OCR split on print L4 (extra token) that would otherwise
    # pull حتى back onto layout line 4.
    kraken_texts = list(HIGH_BODY_LINES)
    kraken_texts[3] = 'الملكين ببابل هاروت و ماروت وما يعلمان من أحد'
    geometry = geometry_from_wide_specs(
        [_wide(y, text) for y, text in zip(HIGH_BODY_YS, kraken_texts)],
    )
    assert geometry.is_empty_top is False
    assert geometry.n_wide == 12
    assert geometry.first_wide_y == 612

    seating = seat_printed_page(
        words=words,
        page_start=0,
        page_end=len(words) - 1,
        starts_by_surah={2: -1},
        geometry=geometry,
        target_lines=12,
    )
    assert seating is not None
    ayahs = _ayah_rows(seating)
    assert len(ayahs) == 12
    line4 = _line_text(words, ayahs[3])
    line5 = _line_text(words, ayahs[4])
    last = _line_text(words, ayahs[11])
    assert line4.endswith('أحد')
    assert not line4.endswith('حتى')
    assert line5.startswith('حتى')
    assert last.startswith('وللكافرين')
    assert words[ayahs[4].start_pos].text == 'حتى'
    assert words[ayahs[11].start_pos].text == 'وللكافرين'


def test_oversize_ayah_slot_splits_into_empty_layout_row():
    """Leftover packing (≥20 words) splits when an empty slot remains."""
    fat = ' '.join(f'كلمة{index:02d}الطويلة' for index in range(1, 31))
    next_line = 'وللكافرين عذاب أليم في ذلكم بلاء'
    words = _words([fat, next_line], surah=2, start_index=1)
    geometry = geometry_from_wide_specs([
        _wide(612, fat),
        _wide(760, next_line),
    ])
    seating = seat_printed_page(
        words=words,
        page_start=0,
        page_end=len(words) - 1,
        starts_by_surah={2: -1},
        geometry=geometry,
        target_lines=12,
    )
    assert seating is not None
    ayahs = _ayah_rows(seating)
    assert len(ayahs) >= 3
    assert max(line.end_pos - line.start_pos + 1 for line in ayahs) < COLLAPSE_WORDS
    assert words[ayahs[-1].start_pos].text == 'وللكافرين'


def test_missing_kraken_lines_fail_open():
    words = _words(HIGH_BODY_LINES[:3], surah=2)
    geometry = page_text_geometry([])
    assert geometry.wide_lines == ()
    assert seat_printed_page(
        words=words,
        page_start=0,
        page_end=len(words) - 1,
        starts_by_surah={2: -1},
        geometry=geometry,
        target_lines=12,
    ) is None
    assert load_kraken_geometries(
        Path('/tmp/mesaha-kraken-missing'), page_min=2, page_max=5,
    ) == {}


def test_kraken_json_payload_parses_wide_lines(tmp_path):
    payload = {
        'lines': [
            {
                'text': 'سورة النساء مدنية',
                'bbox': [400, 380, 1600, 500],
            },
            {
                'text': 'بسم الله الرحمن الرحيم',
                'bbox': [200, 1140, 1860, 1220],
            },
            {
                'text': 'يا أيها الناس اتقوا ربكم الذي خلقكم من نفس',
                'bbox': [90, 1270, 1970, 1354],
                'words': [
                    {'text': part}
                    for part in 'يا أيها الناس اتقوا ربكم الذي خلقكم من نفس'.split()
                ],
            },
        ]
    }
    lines = kraken_lines_from_payload(payload)
    geometry = page_text_geometry(lines)
    assert geometry.has_banner is True
    assert geometry.is_empty_top is True
    assert geometry.n_wide == 1
    assert geometry.wide_lines[0].normalized.startswith('ياايها')

    path = tmp_path / 'p097.json'
    path.write_text(
        '{"lines": [{"text": "يا أيها الناس اتقوا ربكم الذي خلقكم من نفس واحدة",'
        ' "bbox": [90, 1312, 1970, 1390]}]}',
        encoding='utf-8',
    )
    loaded = load_kraken_geometries(tmp_path, page_min=97, page_max=97)
    assert 97 in loaded
    assert loaded[97].n_wide == 1
