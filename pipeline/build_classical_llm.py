#!/usr/bin/env python3
"""AI re-extraction of the classical waqf books → data/classical_waqf.db.

WHY: the regex/cursor extractor in build_classical_waqf.py pattern-matches a
grade word next to a {quote}, which works for entries printed in that exact
shape but fails on the DISCURSIVE prose these books are mostly written in —
so the علّة (the reasoning, the whole point of the «لماذا يُوقف هنا؟» card) is
empty or trimmed for most stops (منار 47% thin, مكتفى 78%, ابن الأنباري 68%),
«وكذا/ومثله» chains collapse to a bare "و", and whole surahs written as prose
(e.g. منار's entire سورة الفاتحة classification — «فالتامة أربعة: البسملة،
والدين، ونستعين، والضالين …») are missed ENTIRELY (0 rows). See the memory
[[muktafa-classical-layer]] for the five rounds of regex patching that never
closed this — it's a reading-comprehension problem, not a regex-tunable one.

WHAT: read each surah's prose from the source book, ask an LLM (offline, at
build time — same philosophy as build_tafseer_local.py: zero AI at request
time) to extract every stop it discusses as strict JSON {ayah, stop_phrase,
grade, reason, reported_from}, then a DETERMINISTIC post-step maps the phrase
to a word position with the SAME battle-tested align_in_ayah() the regex
pipeline uses — which doubles as the anti-hallucination gate: a phrase that
isn't a verbatim run of words in that verse is rejected.

The علّة is kept FAITHFUL to the author's own wording (cleaned/expanded only —
chains resolved, page-markers/poetry stripped), never reinterpreted.

Output: rows written under a SEPARATE source tag (default `manar_llm`) so the
new extraction sits ALONGSIDE the regex `manar` for side-by-side review — the
shipped book is not touched until you approve the diff.

Run (pilot, منار only):
    # 1. no key needed — replays cached responses (e.g. the inline-verified surahs):
    python3 pipeline/build_classical_llm.py --book manar
    # 2. full run — needs an API key; caches each surah so it's resumable & re-runs are free.
    #    Put the key in a project-root .env file (already gitignored) — NEVER paste a key
    #    into a chat/terminal command that gets logged. .env is auto-loaded if present:
    #        ANTHROPIC_API_KEY=sk-...     # for --provider anthropic (default)
    #        GEMINI_API_KEY=...           # for --provider gemini
    python3 pipeline/build_classical_llm.py --book manar --api --provider gemini
    # limit to specific surahs:  --surahs 1,103,108,112,113,114
    # write into the DB (default is dry / stats-only):  --write
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('RESEARCH_PRECOMPUTE', '1')

try:
    from dotenv import load_dotenv                        # optional: auto-load a local .env
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))
except ImportError:
    pass

# Reuse the vetted helpers from the regex builder (grades, normalisation, the
# per-ayah phrase→wpos aligner, source loading, surah-title resolution).
import build_classical_waqf as rx  # noqa: E402
import app  # noqa: E402

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'classical_llm_cache')
SHIPPED_DB = rx.OUT_DB
# Pilot writes to a SEPARATE db by default so the shipped classical_waqf.db (served
# live, unfiltered by source) is never touched with unreviewed rows. Point --db at
# the shipped db only once the extraction is approved for release.
PILOT_DB = os.path.join(app._BASE_DIR, 'data', 'classical_waqf_llm.db')
ANTHROPIC_MODEL = os.environ.get('CLASSICAL_LLM_MODEL', 'claude-sonnet-5')
GEMINI_MODEL = os.environ.get('CLASSICAL_LLM_GEMINI_MODEL', 'gemini-2.5-flash')

_SCHEMA = ('CREATE TABLE IF NOT EXISTS classical ('
           'id INTEGER PRIMARY KEY, source TEXT NOT NULL, surah INTEGER NOT NULL, '
           'ayah INTEGER, wpos INTEGER, stop_word TEXT, quote TEXT NOT NULL, '
           'grade TEXT NOT NULL, grade_raw TEXT NOT NULL, note TEXT, seq INTEGER, '
           'conf INTEGER NOT NULL DEFAULT 1, reported_from TEXT)')

BOOK_NAME_AR = {'manar': 'منار الهدى في بيان الوقف والابتدا',
                'muktafa': 'المكتفى في الوقف والابتدا',
                'nahhas': 'القطع والائتناف', 'anbari': 'إيضاح الوقف والابتداء'}
BOOK_AUTHOR = {'manar': 'الأشموني', 'muktafa': 'الداني', 'nahhas': 'النحاس', 'anbari': 'ابن الأنباري'}

GRADE_SET = sorted(set(v for _, v in rx.GRADES))          # تام كاف حسن جائز صالح قبيح لا
_GRADE_LABEL = {'لا': 'ليس بوقف'}


# Surah name variants the source uses that the shipped ALIASES map lacks — the
# regex منار build inherits the SAME gap and silently drops these surahs (النساء
# is even worse: its header is single-hash «# سورة النساء», stripped by load_book).
# Extend the shared resolver so the AI run covers the WHOLE book, not ~105 surahs.
rx.ALIASES.update({
    'النساء': 4, 'المنافقين': 63, 'المنافقون': 63, 'الانشراح': 94, 'الشرح': 94,
    'لإيلاف قريش': 106, 'قريش': 106, 'الفلق': 113, 'الناس': 114, 'المطففين': 83,
    'التطفيف': 83, 'الرحيق': 83,   # منار titles المطففين «سورة الرحيق»
})

# A surah header line at ANY heading level (OpenITI paragraphs all start with «# »,
# so require the title to START with سورة/فاتحة or be a known combined title —
# a prose line like «# قال في سورة النساء…» is excluded because it starts with قال).
_HEADER_RE = re.compile(r'^#{1,3}[ \t]*\|?[ \t]*((?:سورة|فاتحة)\b.*|الفلق والناس)$')
_COMBINED = {'الفلق والناس': (113, 114)}

# Authoritative per-surah source for منار — converted (pipeline/convert_manar_
# shamela.py) from الأشموني's OWN Shamela book database (the primary source
# OpenITI's plaintext dump was itself digitized from), keyed by the book's own
# table of contents (exact page boundaries, no title-matching guesswork). Fixes
# real gaps the OpenITI-markdown slicer had even after the header-detection fix
# below: النساء and 5 other surahs were silently dropped, and قريش's absence
# (no separate heading — it's discussed inside سورة الفيل's section) turned out
# to be a genuine authorial choice, independently confirmed by Shamela's own
# TOC, not a parsing bug. See pipeline/CLASSICAL_LLM_PILOT.md.
_SHAMELA_SECTIONS = os.path.join(rx.SRC_DIR, 'manar_shamela_sections.json')


def _shamela_surah_blocks():
    sections = json.load(open(_SHAMELA_SECTIONS, encoding='utf-8'))
    for s in range(1, 115):
        sec = sections.get(str(s))
        if sec:
            yield s, sec['title'], sec['text']


# ── slice the source book into per-surah prose blocks ────────────────────────
def surah_blocks(book):
    """Yield (surah_number, name, prose_text) per surah of the book. Prefers
    the authoritative Shamela-derived JSON for منار when present (see above);
    falls back to detecting headers in the OpenITI markdown at any hash level
    (so single-hash «# سورة النساء» is caught, not just «### |»), resolving
    each title with the shared surah_number() + the extended aliases above.
    Combined headers («الفلق والناس») yield both surahs."""
    if book == 'manar' and os.path.exists(_SHAMELA_SECTIONS):
        yield from _shamela_surah_blocks()
        return

    raw = open(os.path.join(rx.SRC_DIR, rx.SOURCES[book]), encoding='utf-8').read()
    raw = raw.split('#META#Header#End#', 1)[1]
    raw = re.sub(r'PageV\d+P\d+|\bms\d+\b|\[\s*\d+\s*/\s*\d+\s*\]', ' ', raw)

    def clean(lines):
        t = '\n'.join(lines)
        t = t.replace('\n~~', ' ').replace('\n# ', '\n')   # OpenITI: join continuations, drop para marks
        return t.strip()

    last = 0
    pending = []          # (surah, name) awaiting their shared body (for combined headers)
    buf = []

    def flush():
        for s, nm in pending:
            yield s, nm, clean(buf)

    for line in raw.split('\n'):
        m = _HEADER_RE.match(line.strip())
        title = m.group(1).strip() if m else None
        nums = None
        if title:
            if title in _COMBINED:
                nums = _COMBINED[title]
            else:
                n = rx.surah_number(title, last)
                nums = (n,) if n else None
        # Boundary only if it resolves to a LATER surah — the book runs in mushaf
        # order, so this rejects a prose line that merely opens with «سورة X»
        # (which would resolve to an already-passed surah, not a new one).
        if nums and min(nums) > last:
            yield from flush()
            pending, buf, last = [(s, title) for s in nums], [], max(nums)
        elif pending:
            buf.append(line)
    yield from flush()


def verses_block(surah):
    """The surah's verses as `آية N: w0 w1 w2 …` lines (raw mushaf words), for
    the prompt — the model copies the stop word verbatim from here."""
    lines, n = [], 0
    while True:
        vk = f'{surah}:{n + 1}'
        if vk not in app.qpc_hafs_data_normalized:
            break
        n += 1
        _, words, _ = app._verse_word_texts(vk)
        lines.append(f'آية {n}: ' + ' '.join(words))
    return '\n'.join(lines), n


# ── prompt (faithful-to-source extraction) ───────────────────────────────────
def build_messages(book, surah, name, prose, verses):
    author = BOOK_AUTHOR[book]
    system = (
        f'أنت باحثٌ متخصّص في علم الوقف والابتداء. مهمتك استخراج مواضع الوقف التي '
        f'ذكرها {author} في كتاب «{BOOK_NAME_AR[book]}» لسورةٍ واحدة، من النصّ '
        f'المُعطى فقط، بأمانةٍ تامّة ودون أي إضافةٍ أو اجتهادٍ من عندك.\n\n'
        'أخرِج مصفوفة JSON فقط (بلا أي نصٍّ آخر)، كل عنصرٍ فيها موضع وقفٍ واحد بالحقول:\n'
        '- "ayah": رقم الآية (عدد صحيح) كما يظهر في قائمة الآيات المُعطاة.\n'
        '- "stop_phrase": الكلمة (أو الكلمتان/الثلاث) التي يُوقف عندها، منقولةً '
        'حرفيًّا من نصّ تلك الآية في القائمة المُعطاة — آخر كلمةٍ قبل الوقف. '
        'انسخها بالرسم نفسه الوارد في القائمة.\n'
        f'- "grade": حكم الوقف، واحدٌ فقط من: {"، ".join(GRADE_SET)} '
        '(استعمل "لا" لِما نصّ المؤلف على أنه ليس بوقفٍ أو يقبح الوقف عليه).\n'
        '- "reason": علّة الوقف بكلام المؤلف نفسه، منقّحةً: احذف علامات الصفحات '
        'والحواشي والاستطراد الشعري والنحوي الطويل؛ وإذا أحال بـ«وكذا/ومثله» '
        'فاذكر صراحةً المواضع التي أحال إليها؛ ولا تُضِف تفسيرًا من عندك. '
        'إن لم يذكر المؤلف علّةً فاترك الحقل نصًّا فارغًا "".\n'
        '- "reported_from": اسم العالِم إن كان المؤلف يَنقل قوله («وقال فلان: …») '
        'وإلا null.\n\n'
        'قواعد صارمة: (أ) استخرِج فقط المواضع التي ناقشها المؤلف في هذا النصّ. '
        '(ب) قد يذكر المؤلف الأحكام نثرًا («فالتامة أربعة: كذا وكذا…») لا في صيغة '
        '{كذا} — استخرِجها جميعًا. (ج) stop_phrase يجب أن تكون موجودةً حرفيًّا في '
        'الآية المذكورة. (د) لا تختلق موضعًا ولا حكمًا ولا علّة.'
    )
    user = (f'السورة: {name} (رقم {surah}).\n\nآيات السورة (انسخ منها stop_phrase حرفيًّا):\n'
            f'{verses}\n\n=== نصّ {BOOK_NAME_AR[book]} لهذه السورة ===\n{prose}')
    return system, user


# ── extractor backends: cache (free, resumable) or the Claude API ────────────
def cache_path(book, surah):
    return os.path.join(CACHE_DIR, f'{book}_{surah:03d}.json')


def load_cached(book, surah):
    p = cache_path(book, surah)
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return None


def call_anthropic_api(book, surah, name, prose, verses):
    import anthropic                                       # lazy: only needed for --api
    system, user = build_messages(book, surah, name, prose, verses)
    client = anthropic.Anthropic()                         # reads ANTHROPIC_API_KEY from env
    msg = client.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=8192, system=system,
        messages=[{'role': 'user', 'content': user}])
    text = ''.join(b.text for b in msg.content if getattr(b, 'type', '') == 'text')
    return parse_json_array(text)


def call_gemini_api(book, surah, name, prose, verses):
    from google import genai                               # lazy: pip install google-genai
    from google.genai import types
    system, user = build_messages(book, surah, name, prose, verses)
    client = genai.Client()                                # reads GEMINI_API_KEY from env
    resp = client.models.generate_content(
        model=GEMINI_MODEL, contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type='application/json'))
    return parse_json_array(resp.text or '[]')


_PROVIDERS = {'anthropic': call_anthropic_api, 'gemini': call_gemini_api}


def call_api(provider, book, surah, name, prose, verses):
    stops = _PROVIDERS[provider](book, surah, name, prose, verses)
    os.makedirs(CACHE_DIR, exist_ok=True)
    json.dump(stops, open(cache_path(book, surah), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return stops


def parse_json_array(text):
    text = text.strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?|```$', '', text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', text, re.S)
        return json.loads(m.group(0)) if m else []


# ── deterministic align + validate (the anti-hallucination gate) ─────────────
def align_stops(surah, stops):
    """Turn raw LLM stops into DB rows, dropping anything that fails validation.
    Returns (rows, stats). A stop is confident iff: grade ∈ lexicon AND its
    phrase maps to a real word position in the stated ayah (align_in_ayah)."""
    rows, stats = [], {'in': len(stops), 'bad_grade': 0, 'bad_ayah': 0, 'unaligned': 0, 'ok': 0}
    acount = rx.surah_ayah_count(surah)
    for i, s in enumerate(stops):
        grade = (s.get('grade') or '').strip()
        if grade not in GRADE_SET:
            stats['bad_grade'] += 1
            continue
        try:
            ayah = int(s.get('ayah'))
        except (TypeError, ValueError):
            stats['bad_ayah'] += 1
            continue
        if not (1 <= ayah <= acount):
            stats['bad_ayah'] += 1
            continue
        phrase = (s.get('stop_phrase') or '').strip()
        qwords = rx.quote_words(phrase)
        wpos, level = rx.align_in_ayah(surah, ayah, qwords)
        if wpos is None:
            stats['unaligned'] += 1                        # phrase not verbatim in verse → reject (hallucination guard)
            continue
        _, words, _ = app._verse_word_texts(f'{surah}:{ayah}')
        stop_word = words[wpos] if 0 <= wpos < len(words) else phrase
        reason = rx.clean_note(s.get('reason') or '')
        reported = (s.get('reported_from') or None)
        if isinstance(reported, str):
            reported = reported.strip() or None
        rows.append((surah, ayah, wpos, stop_word, phrase, grade, _GRADE_LABEL.get(grade, grade),
                     reason, i, 1, reported))
        stats['ok'] += 1
    return rows, stats


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book', default='manar', choices=list(rx.SOURCES))
    ap.add_argument('--surahs', help='comma list to limit (e.g. 1,103,112); default all')
    ap.add_argument('--api', action='store_true', help='call the LLM API for surahs not cached')
    ap.add_argument('--provider', default='anthropic', choices=list(_PROVIDERS),
                    help='which API to call with --api (needs ANTHROPIC_API_KEY or GEMINI_API_KEY '
                         'set — e.g. in a project-root .env file, auto-loaded)')
    ap.add_argument('--write', action='store_true', help='store rows in the db (else dry / stats-only)')
    ap.add_argument('--source-tag', default=None, help='DB source column value (default <book>_llm)')
    ap.add_argument('--db', default=PILOT_DB,
                    help=f'target sqlite db (default the PILOT db {os.path.basename(PILOT_DB)}; '
                         'pass the shipped classical_waqf.db only when releasing)')
    ap.add_argument('--status', action='store_true',
                    help='list which surahs are already extracted (cached) vs still to do, then exit')
    args = ap.parse_args()

    if args.status:
        done, todo = [], []
        for surah, name, _ in surah_blocks(args.book):
            (done if load_cached(args.book, surah) is not None else todo).append(surah)
        print(f'{args.book}: {len(done)} surahs cached (no API needed), {len(todo)} remaining.')
        print(f'  cached : {done}')
        print(f'  to do  : {todo}')
        print(f'\nrun `--api --write` to extract the {len(todo)} remaining (cached ones are reused).')
        return
    only = set(int(x) for x in args.surahs.split(',')) if args.surahs else None
    tag = args.source_tag or f'{args.book}_llm'

    all_rows, totals = [], {'in': 0, 'bad_grade': 0, 'bad_ayah': 0, 'unaligned': 0, 'ok': 0, 'surahs': 0, 'missing': 0}
    for surah, name, prose in surah_blocks(args.book):
        if only and surah not in only:
            continue
        verses, _ = verses_block(surah)
        stops = load_cached(args.book, surah)
        if stops is None:
            if args.api:
                print(f'  · surah {surah:3} — calling {args.provider}…', flush=True)
                stops = call_api(args.provider, args.book, surah, name, prose, verses)
            else:
                totals['missing'] += 1
                continue
        rows, st = align_stops(surah, stops)
        all_rows.extend((tag, *r) for r in rows)
        for k in ('in', 'bad_grade', 'bad_ayah', 'unaligned', 'ok'):
            totals[k] += st[k]
        totals['surahs'] += 1
        with_reason = sum(1 for r in rows if len((r[7] or '').strip()) >= 18)
        print(f'  surah {surah:3} {name[:22]:22}  stops {st["in"]:3} → confident {st["ok"]:3}'
              f'  (with علّة {with_reason:3})  [reject: grade {st["bad_grade"]}, ayah {st["bad_ayah"]}, unaligned {st["unaligned"]}]')

    print(f'\n{args.book}: {totals["surahs"]} surahs processed, {totals["missing"]} not cached (skipped).')
    print(f'  {totals["in"]} raw stops → {totals["ok"]} confident rows '
          f'({totals["unaligned"]} rejected as unaligned, {totals["bad_grade"]} bad grade, {totals["bad_ayah"]} bad ayah).')
    with_reason = sum(1 for r in all_rows if len((r[8] or '').strip()) >= 18)
    print(f'  rows with a real علّة (≥18 chars): {with_reason}/{len(all_rows)} '
          f'({100 * with_reason / max(1, len(all_rows)):.0f}%)')

    if not args.write:
        print('\n(dry run — pass --write to store these rows under source=' + tag + ')')
        return
    import sqlite3
    conn = sqlite3.connect(args.db)
    conn.execute(_SCHEMA)                              # no-op if it already exists (shipped db)
    conn.execute('CREATE INDEX IF NOT EXISTS idx_classical_verse ON classical(surah, ayah)')
    conn.execute('DELETE FROM classical WHERE source = ?', (tag,))
    conn.executemany(
        'INSERT INTO classical (source, surah, ayah, wpos, stop_word, quote, grade, '
        'grade_raw, note, seq, conf, reported_from) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', all_rows)
    conn.commit()
    conn.close()
    print(f'\nwrote {len(all_rows)} rows under source={tag} into {args.db}')


if __name__ == '__main__':
    main()
