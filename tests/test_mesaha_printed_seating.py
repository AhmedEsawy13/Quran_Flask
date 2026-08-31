"""Mesaha printed-line seating from Kraken wide-line geometry.

These fixtures do not need mushaf DBs or Ahmed's 826 Kraken JSON files.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipeline.mesaha_printed_seating import (
    COLLAPSE_WORDS,
    EMPTY_TOP_Y_JPEG,
    JPEG_TEXT_BOTTOM,
    JPEG_TEXT_TOP,
    LINE_Y_MERGE,
    KrakenLine,
    _bbox_from_raw,
    clip_empty_top_page_starts,
    geometry_from_wide_specs,
    kraken_lines_from_payload,
    load_kraken_geometries,
    load_kraken_page,
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


def test_p20_adjacent_wide_ayahs_dy149_are_not_merged_and_wrap():
    """Production k08 y=928 and k09 y=1077 (dy=149) stay two ayahs; wrap at أحد."""
    ys = [612, 761, 928, 1077, 1226, 1375, 1524, 1673, 1822, 1971, 2120, 2269]
    assert ys[3] - ys[2] == 149
    assert ys[3] - ys[2] < LINE_Y_MERGE
    geometry = geometry_from_wide_specs(
        [_wide(y, text) for y, text in zip(ys, HIGH_BODY_LINES)],
    )
    assert geometry.n_wide == 12
    assert geometry.wide_lines[2].y == 928
    assert geometry.wide_lines[3].y == 1077
    assert 'أحد' in geometry.wide_lines[3].text
    assert geometry.wide_lines[4].text.startswith('حتى')

    words = _words(HIGH_BODY_LINES, surah=2, start_index=400, start_ayah=101)
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
    assert _line_text(words, ayahs[3]).endswith('أحد')
    assert _line_text(words, ayahs[4]).startswith('حتى')
    assert words[ayahs[4].start_pos].text == 'حتى'


def test_empty_top_pulls_stolen_surah_first_word_and_seats_headers():
    """p97: 4:1:1 was left on p96; clip must pull يا أيها back and insert banner."""
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
    ]
    body = _words(body_lines, surah=4, start_index=10169, start_ayah=1)
    words = leftover + body
    surah_first = len(leftover)  # يا
    assert words[surah_first].text == 'يا'
    assert words[surah_first + 2].text == 'الناس'
    starts_by_surah = {3: -1, 4: surah_first}
    # Page 97 currently starts at الناس (4:1:2), 4:1:1 left on page 96.
    starts = [0, surah_first + 2, len(words)]
    ocr_lines = list(body_lines)
    ocr_lines[0] = 'كايها الناس اتقوا ربكم الذي خلقكم من نفس'
    ys = [1251 + i * 150 for i in range(7)]
    geometry = geometry_from_wide_specs(
        [_wide(y, text) for y, text in zip(ys, ocr_lines)],
        banner_text='سورة النساء مدنية',
        banner_y=420,
        basmala_text='بسم الله الرحمن الرحيم',
        basmala_y=1180,
    )
    assert geometry.is_empty_top is True
    assert geometry.first_wide_y == 1251
    assert geometry.n_wide == 7

    clip_empty_top_page_starts(
        starts, words, {97: geometry}, starts_by_surah, page_min=96,
    )
    assert starts[1] == surah_first
    assert starts[0] < starts[1]

    seating = seat_printed_page(
        words=words,
        page_start=starts[1],
        page_end=len(words) - 1,
        starts_by_surah=starts_by_surah,
        geometry=geometry,
        target_lines=12,
    )
    assert seating is not None
    header_types = [
        line.line_type for line in seating.lines if line.line_type != 'ayah'
    ]
    assert header_types == ['surah_name', 'surah_info', 'basmallah']
    assert [line.line_number for line in seating.lines if line.line_type != 'ayah'] == [1, 2, 3]
    ayahs = _ayah_rows(seating)
    assert words[ayahs[0].start_pos].text == 'يا'
    assert ayahs[0].surah == 4
    # Fuzzy OCR كايها must not skip يا أيها once 4:1:1 is on the page.
    assert _line_text(words, ayahs[0]).startswith('يا أيها')


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


def test_short_juz_amma_page_pads_empty_slots_instead_of_throwing():
    """p822: 5 words of قريش, empty-top, 3 headers, 12 lines — no throw."""
    words = _words(
        ['لإيلاف قريش ١', 'إيلافهم رحلة'],
        surah=106,
        start_index=1,
        start_ayah=1,
    )
    assert len(words) == 5
    assert words[0].word_key == '106:1:1'
    assert words[-1].word_key == '106:2:2'

    body_lines = [
        'لإيلاف قريش إيلافهم رحلة الشتاء',
        'سطر تال كاف للعرض العريض هنا واحد',
        'سطر تال كاف للعرض العريض هنا اثنان',
        'سطر تال كاف للعرض العريض هنا ثلاثة',
        'سطر تال كاف للعرض العريض هنا أربعة',
        'سطر تال كاف للعرض العريض هنا خمسة',
        'سطر تال كاف للعرض العريض هنا ستة',
        'سطر تال كاف للعرض العريض هنا سبعة',
        'سطر تال كاف للعرض العريض هنا ثمانية',
    ]
    ys = [1312 + index * 120 for index in range(9)]
    geometry = geometry_from_wide_specs(
        [_wide(y, text) for y, text in zip(ys, body_lines)],
        banner_text='سورة قريش مكية',
        banner_y=420,
        basmala_text='بسم الله الرحمن الرحيم',
        basmala_y=1180,
    )
    assert geometry.is_empty_top is True
    assert geometry.n_wide == 9
    assert geometry.first_wide_y >= EMPTY_TOP_Y_JPEG

    seating = seat_printed_page(
        words=words,
        page_start=0,
        page_end=len(words) - 1,
        starts_by_surah={106: 0},
        geometry=geometry,
        target_lines=12,
    )
    assert seating is not None
    assert len(seating.lines) == 12
    headers = [line for line in seating.lines if line.line_type != 'ayah']
    assert [line.line_type for line in headers] == [
        'surah_name', 'surah_info', 'basmallah',
    ]
    filled = _ayah_rows(seating)
    assert len(filled) == 1
    assert filled[0].start_pos == 0
    assert filled[0].end_pos == 4
    empty_ayahs = [
        line for line in seating.lines
        if line.line_type == 'ayah' and line.start_pos is None
    ]
    assert len(empty_ayahs) == 8
    assert _line_text(words, filled[0]).split()[0] == 'لإيلاف'
    assert words[filled[0].end_pos].text == 'رحلة'


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


def test_bbox_from_raw_reads_p020_keys_without_bbox():
    """Exact production line dict — no bbox, single JPEG y."""
    raw = {
        'text': 'الحـزء الأوّل)',
        'y': 331,
        'x0': 867,
        'x1': 1198,
        'width': 331,
    }
    assert 'bbox' not in raw and 'box' not in raw
    box = _bbox_from_raw(raw)
    assert box is not None
    x0, y0, x1, y1 = box
    assert (x0, x1) == (867, 1198)
    assert y0 == 331
    assert y1 > y0
    parsed = kraken_lines_from_payload({
        'image': 'p020.jpg',
        'width': 2062,
        'height': 3023,
        'n_lines': 1,
        'lines': [raw],
    })
    assert parsed != []
    assert parsed[0].y == 331
    assert parsed[0].width == 331


def _production_line(text: str, y: int, *, x0: int = 80, x1: int = 1980) -> dict:
    """Real Ahmed Kraken page JSON line: text/y/x0/x1/width, no bbox."""
    return {
        'text': text,
        'y': y,
        'x0': x0,
        'x1': x1,
        'width': x1 - x0,
    }


def test_production_kraken_json_keys_load_wide_lines_and_wrap(tmp_path):
    """p020.json shape: image/width/height/n_lines + lines without bbox."""
    payload = {
        'image': 'p020.jpg',
        'width': 2062,
        'height': 3023,
        'n_lines': 13,
        'lines': [
            _production_line('الحـزء الأوّل)', 331, x0=867, x1=1198),
            *[
                _production_line(text, y)
                for y, text in zip(HIGH_BODY_YS, HIGH_BODY_LINES)
            ],
        ],
    }
    lines = kraken_lines_from_payload(payload)
    assert len(lines) == 13
    assert 'bbox' not in payload['lines'][0]
    assert lines[1].y == 612
    geometry = page_text_geometry(lines)
    assert geometry.n_wide == 12
    assert geometry.first_wide_y == 612
    assert geometry.is_empty_top is False

    words = _words(HIGH_BODY_LINES, surah=2, start_index=400, start_ayah=101)
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
    assert _line_text(words, ayahs[3]).endswith('أحد')
    assert _line_text(words, ayahs[4]).startswith('حتى')
    assert _line_text(words, ayahs[11]).startswith('وللكافرين')

    path = tmp_path / 'p020.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    loaded_lines = load_kraken_page(path)
    assert len(loaded_lines) == 13
    assert all(line.width == line.x1 - line.x0 for line in loaded_lines)
    loaded = load_kraken_geometries(tmp_path, page_min=20, page_max=20)
    assert loaded[20].n_wide == 12
    assert loaded[20].first_wide_y == 612


def test_production_kraken_json_keys_empty_top_p097():
    banner = _production_line('سورة النساء مدنية', 420, x0=400, x1=1600)
    basmala = _production_line('بسم الله الرحمن الرحيم', 1180, x0=200, x1=1800)
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
    ys = [1312 + i * 150 for i in range(8)]
    payload = {
        'image': 'p097.jpg',
        'width': 2062,
        'height': 3023,
        'n_lines': 10,
        'lines': [banner, basmala] + [
            _production_line(text, y) for y, text in zip(ys, body_lines)
        ],
    }
    geometry = page_text_geometry(kraken_lines_from_payload(payload))
    assert geometry.n_wide == 8
    assert geometry.first_wide_y == 1312
    assert geometry.is_empty_top is True


def test_present_kraken_file_with_unparsed_lines_does_not_fail_open(tmp_path):
    """826 files loaded / 0 geometry must raise, not skip to DjVu even-split."""
    import pytest

    payload = {
        'image': 'p020.jpg',
        'width': 2062,
        'height': 3023,
        'n_lines': 1,
        'lines': [{'text': 'الحـزء الأوّل)', 'mystery': True}],
    }
    with pytest.raises(ValueError, match='none produced geometry'):
        kraken_lines_from_payload(payload)
    (tmp_path / 'p020.json').write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding='utf-8',
    )
    with pytest.raises(ValueError, match='none produced geometry'):
        load_kraken_geometries(tmp_path, page_min=20, page_max=20)
