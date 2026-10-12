"""Arabic review page for a ``book_audit`` run.

    python -m pipeline.cv_waqf book-review --edition الكويت [--dir DIR]

Reads ``pages.jsonl`` and writes ``review.html``, ``summary.json`` and
``candidates.csv`` next to it. Optional ``notes.json`` ({crop file: note}) puts a
reviewer's note on a card. For cloud editions the current draft/published marks
are read (read-only) so finished items show as done.

Tabs, most urgent first: a sign the DB has on one word but the scan shows on its
neighbour even without the Madinah adjustment (``shift``), additions, sign
differences (ordered by how the reference prints lean), DB marks not seen; and
for reference only: neighbour cases the unbiased pass settles in the DB's favour
(``resolved``) and DB marks found printed by ``verify_claims`` (``confirmed``).
The reference prints (المدينة الجديد/القديم، الأزهر) only ORDER and badge the
cards — deciding by them would hide an edition's genuine differences.
"""
from __future__ import annotations

import csv
import html
import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote

from pipeline.cv_waqf.config import EDITIONS

# The cloud-backed editor (launch config quran-flask-cloud): cloud editions are
# edited as Supabase drafts there. The :5001 dev server runs without Supabase
# and refuses those edits.
EDITOR = 'http://localhost:5002/mushaf-editor'
# Approve / reject each card in the cloud (modules/audit_review.py).
IN_EDITOR_REVIEW = 'http://localhost:5002/mushaf-editor/book-audit'
REFS = ('المدينة الجديد', 'المدينة القديم', 'الأزهر')
SYM = {'ص': 'صلى', 'ج': 'جائز', 'ق': 'قلى', 'لا': 'لا', 'م': 'لازم', 'س': 'سكتة', 'ع': 'معانقة'}
SURAHS = (
    'الفاتحة البقرة آل_عمران النساء المائدة الأنعام الأعراف الأنفال التوبة يونس هود يوسف الرعد إبراهيم الحجر '
    'النحل الإسراء الكهف مريم طه الأنبياء الحج المؤمنون النور الفرقان الشعراء النمل القصص العنكبوت الروم لقمان '
    'السجدة الأحزاب سبأ فاطر يس الصافات ص الزمر غافر فصلت الشورى الزخرف الدخان الجاثية الأحقاف محمد الفتح '
    'الحجرات ق الذاريات الطور النجم القمر الرحمن الواقعة الحديد المجادلة الحشر الممتحنة الصف الجمعة المنافقون '
    'التغابن الطلاق التحريم الملك القلم الحاقة المعارج نوح الجن المزمل المدثر القيامة الإنسان المرسلات النبأ '
    'النازعات عبس التكوير الانفطار المطففين الانشقاق البروج الطارق الأعلى الغاشية الفجر البلد الشمس الليل '
    'الضحى الشرح التين العلق القدر البينة الزلزلة العاديات القارعة التكاثر العصر الهمزة الفيل قريش الماعون '
    'الكوثر الكافرون النصر المسد الإخلاص الفلق الناس'
).replace('_', ' ').split(' ')
SURAHS = [n.replace('آل', 'آل عمران') if n == 'آل' else n for n in SURAHS if n != 'عمران']
esc = html.escape


def _key(i):
    return tuple(int(x) for x in i['word_key'].split(':'))


def classify_items(items: list[dict]) -> list[dict]:
    """Re-kind the audit's items for review.

    A DB mark the scan did not see (``cv_missed``) next to a sign the scan shows
    on the neighbouring word (``not_in_db``) is one case, not two:
    - ``resolved``: without the Madinah adjustment the sign attaches to the DB's
      word — the detector's pull, not the DB, was wrong;
    - ``shift``: the same sign, and even the unbiased pass keeps it on the
      neighbour — a real one-word-off candidate;
    - ``shift_unsure``: same sign, no unbiased owner to tell.
    Then DB marks the image confirms (``item['verify']['found']``) become
    ``confirmed``.
    """
    detected = {(i['page'], *_key(i)): i for i in items if i['kind'] in ('not_in_db', 'symbol_differs')}
    paired, extra = set(), []
    for i in items:
        if i['kind'] != 'cv_missed':
            continue
        s, a, w = _key(i)
        for d in (-1, 1):
            j = detected.get((i['page'], s, a, w + d))
            if j is None or j['kind'] != 'not_in_db' or id(j) in paired:
                continue
            raw = (j.get('raw') or {}).get('raw_key')
            if raw == i['word_key']:
                kind = 'resolved' if j['cv'] == i['db'] else 'symbol_differs_geo'
            elif j['cv'] != i['db']:
                continue
            elif raw == j['word_key']:
                kind = 'shift'
            else:
                kind = 'shift_unsure'
            extra.append(dict(j, kind=kind, db=i['db'], from_key=i['word_key'], from_text=i['text'],
                              from_crop=i['crop'], others=i['others']))
            paired.update((id(i), id(j)))
            break
    out = [i for i in items if id(i) not in paired] + extra
    for i in out:
        v = i.get('verify') or {}
        if v.get('found') and i['kind'] in ('symbol_differs', 'symbol_differs_geo', 'cv_missed'):
            i.update(kind='confirmed', from_crop=i['crop'], crop=v['crop'], verify_p=v['p'])
    return out


def ref_lean(i: dict) -> int:
    """+n: n reference prints agree with the scan and not with the DB; -n: the
    other way round. الأزهر prints only ج/م/لا, so it counts only for those."""
    o = i.get('others') or {}
    cv, db = i.get('cv') or '', i.get('db') or ''
    lean = 0
    for ref in REFS:
        if ref == 'الأزهر' and (cv in ('ق', 'ص') or db in ('ق', 'ص')):
            continue
        v = o.get(ref, '')
        lean += (v == cv) - (v == db)
    return lean


TABS = [
    ('shift', 'انتقال إلى كلمة مجاورة',
     'العلامة مسجّلة على كلمة، والنموذج يراها على جارتها — حتى بعد إيقاف ترجيحه بالمصاحف الأخرى. أقوى المرشّحات لخطأ «كلمة واحدة» في القاعدة — الأولوية الأولى.',
     lambda i: i['kind'] == 'shift'),
    ('shift_unsure', 'انتقال — غير حاسم',
     'مثل السابق، لكن تعذّر حساب الإلحاق بلا ترجيح لهذه العلامة. انظر الصورتين.',
     lambda i: i['kind'] == 'shift_unsure'),
    ('add', 'للإضافة إلى المصحف',
     'علامات ظاهرة في صورة المصحف وغير مسجّلة في القاعدة، ثقة الكشف ٩٩٪ فأكثر.',
     lambda i: i['kind'] == 'not_in_db' and i['conf'] >= 0.99),
    ('maybe', 'تحتاج نظرًا',
     'ثقة أقل من ٩٩٪. كثير منها حركات أو نقاط حروف، وبعضها علامات حقيقية.',
     lambda i: i['kind'] == 'not_in_db' and i['conf'] < 0.99),
    ('differs', 'اختلاف الرمز',
     'النموذج والقاعدة متفقان على موضع الوقف ومختلفان في الرمز. الشارة الصفراء: المراجع تؤيد الصورة (الأرجح خطأ في القاعدة)؛ الخضراء: تؤيد القاعدة.',
     lambda i: i['kind'] in ('symbol_differs', 'symbol_differs_geo')),
    ('missed', 'مسجّلة ولم تُكتشف',
     'علامات في القاعدة لم يجدها النموذج ولم يُعثر عليها مطبوعة قرب آخر الكلمة؛ الإطار يبيّن الكلمة.',
     lambda i: i['kind'] == 'cv_missed'),
    ('resolved', 'حسمتها الهندسة',
     'النموذج ألحق العلامة بالكلمة المجاورة لأن المصاحف الأخرى تضع وقفها هناك؛ وبلا هذا الترجيح يُلحقها بكلمة القاعدة. فالقاعدة صحيحة على الأرجح. للاطلاع فقط.',
     lambda i: i['kind'] == 'resolved'),
    ('confirmed', 'القاعدة مؤكَّدة بالصورة',
     'العلامة التي في القاعدة لهذه الكلمة وُجدت مطبوعةً عند آخرها (الصورة الأولى، الإطار الأخضر) بثقة ٩٥٪ فأكثر — والنموذج قرأ حركةً قريبة أو لم يرها (الصورة الثانية). للاطلاع فقط.',
     lambda i: i['kind'] == 'confirmed'),
]
PRIORITY_TABS = ('shift', 'add', 'maybe', 'differs')


def _load_cloud(edition: str, recs):
    """Read-only: ({(surah, ayah, token): symbol}, pending keys) from cloud
    draft over published; cloud token = layout word position - 1."""
    from core.config import PUBLIC_CLOUD_WAQF_EDITIONS
    if edition not in PUBLIC_CLOUD_WAQF_EDITIONS:
        return None, set()
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / '.env')
        from core import supabase_editor as sb
        keys = sorted({_key(i)[:2] for r in recs for i in r['items']})
        draft, pub = sb.fetch_draft_and_published_for_ayahs(edition=edition, ayah_keys=keys)
    except Exception as exc:  # noqa: BLE001
        print('cloud unavailable:', exc)
        return None, set()

    def idx(rows):
        return {(int(r['surah']), int(r['ayah']), int(r['token_index'])): (r.get('symbol') or '').strip() for r in rows}
    published, drafts = idx(pub), idx(draft)
    merged = dict(published)
    merged.update(drafts)
    return merged, {k for k, v in drafts.items() if v != published.get(k, '')}


def build(edition: str, out_dir: Path) -> dict:
    spec_id = EDITIONS[edition].id
    stamp = f'فحص {date.today().isoformat()}'
    recs = sorted((json.loads(line) for line in (out_dir / 'pages.jsonl').open()), key=lambda r: r['page'])
    notes = json.loads((out_dir / 'notes.json').read_text()) if (out_dir / 'notes.json').exists() else {}
    cloud, pending = _load_cloud(edition, recs)
    tot = Counter()
    for r in recs:
        tot.update(r.get('counts', {}))
    items = classify_items([dict(it, page=r['page']) for r in recs for it in r['items']])

    def cloud_at(key):
        s, a, w = (int(x) for x in key.split(':'))
        return (cloud or {}).get((s, a, w - 1)), (s, a, w - 1) in pending

    for i in items:
        i['conf'] = i.get('conf') or 0
        c, pend = cloud_at(i['word_key'])
        i['cloud'], i['pending'] = c, pend
        if i['kind'] == 'not_in_db':
            i['done'] = bool(c) and not pend
        elif i['kind'] == 'symbol_differs':
            i['done'] = c is not None and c != i['db'] and not pend
        elif i.get('from_key'):
            old, opend = cloud_at(i['from_key'])
            i['pending'] = pend or opend
            i['done'] = c == i['db'] and not old and not i['pending']
        else:
            i['done'] = False

    db_total = tot['match'] + tot['wrong'] + tot['missing']
    summary = {'edition': edition, 'pages': len(recs), 'errors': sum(1 for r in recs if r.get('error')),
               **tot, 'db_waqf_marks_on_pages': db_total,
               'exact_recall': round(tot['match'] / max(1, db_total), 4),
               'tabs': {k: sum(1 for i in items if f(i)) for k, _, _, f in TABS}}
    (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    with (out_dir / 'candidates.csv').open('w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['tab', 'page', 'word_key', 'text', 'db', 'cv', 'conf', *REFS, 'crop'])
        for k, _, _, f in TABS:
            for i in items:
                if f(i):
                    w.writerow([k, i['page'], i['word_key'], i['text'], i['db'] or '', i['cv'] or '', i['conf'] or '',
                                *((i.get('others') or {}).get(r, '') for r in REFS), 'crops/' + i['crop']])
    # The editor's in-app review (/mushaf-editor/audit) reads this queue.
    keep = ('page', 'word_key', 'text', 'db', 'cv', 'conf', 'others', 'crop', 'from_key', 'from_text', 'from_crop')
    queue = {'edition': edition, 'built': stamp, 'summary': summary,
             'tabs': [{'id': k, 'title': title, 'note': note} for k, title, note, _ in TABS],
             'items': [dict({f: i.get(f) for f in keep}, tab=k, lean=ref_lean(i), note=notes.get(i['crop']) or '')
                       for k, _, _, f in TABS for i in items if f(i)]}
    (out_dir / 'queue.json').write_text(json.dumps(queue, ensure_ascii=False))

    def surah_name(n):
        return SURAHS[n - 1] if 0 < n <= len(SURAHS) else str(n)

    def editor_link(page):
        return f'{EDITOR}?edition={quote(edition)}&page={page}'

    def sym_badge(s, cls=''):
        if not s:
            return '<span class="sym none">—</span>'
        return f'<span class="sym {cls}" title="{esc(SYM.get(s, s))}">{esc(s)}</span>'

    def ref_badge(i):
        lean = ref_lean(i)
        if lean > 0:
            return '<div class="ref img">المراجع تؤيد الصورة <small>(المدينة/الأزهر) — الأرجح خطأ في القاعدة</small></div>'
        if lean < 0:
            return '<div class="ref db">المراجع تؤيد القاعدة <small>(المدينة/الأزهر) — الأرجح خطأ قراءة</small></div>'
        return ''

    def raw_line(i):
        g = i.get('raw') or {}
        if not g.get('raw_key') or g['raw_key'] == i['word_key']:
            return ''
        return f'<div class="geo diff">بلا ترجيح المصاحف الأخرى يُلحِق النموذجُ العلامةَ بـ«{esc(g["raw_text"])}»</div>'

    def chip(i, tab):
        s, a, wd = _key(i)
        where = f'{surah_name(s)} · آية {a} · كلمة {wd}'
        others = ''.join(f'<span class="oth"><i>{esc(k.replace("المدينة ", "م. "))}</i>{esc(v)}</span>'
                         for k, v in (i.get('others') or {}).items())
        if tab == 'confirmed':
            verdict = (f'<div class="verdict">في القاعدة {sym_badge(i["db"], "db")} — وُجدت مطبوعة'
                       f'<small>ثقة {i["verify_p"]:.0%}</small></div>')
        elif tab in ('shift', 'shift_unsure', 'resolved'):
            verdict = (f'<div class="verdict">في القاعدة على «{esc(i["from_text"])}» {sym_badge(i["db"], "db")} ← '
                       f'في الصورة على «{esc(i["text"])}» {sym_badge(i["cv"], "cv")}<small>ثقة {i["conf"]:.0%}</small></div>')
        elif tab in ('add', 'maybe'):
            verdict = f'<div class="verdict">أضِف {sym_badge(i["cv"], "cv")}<small>ثقة {i["conf"]:.0%}</small></div>'
        elif tab == 'differs':
            verdict = (f'<div class="verdict">القاعدة {sym_badge(i["db"], "db")} ← النموذج {sym_badge(i["cv"], "cv")}'
                       f'<small>ثقة {i["conf"]:.0%}</small></div>')
        else:
            verdict = f'<div class="verdict">في القاعدة {sym_badge(i["db"], "db")}<small>لم يُكتشف</small></div>'
        cid = esc(i['crop'])
        status = ''
        if i['pending']:
            status = (f'<div class="stat-done pend">✎ مسودة بانتظار النشر: {sym_badge(i["cloud"], "cloud")} '
                      f'<small>راجِعها ثم انشرها من المحرر</small></div>')
        elif i['done']:
            same = i['cloud'] == i['cv']
            status = (f'<div class="stat-done {"same" if same else "diff"}">✓ في السحابة: {sym_badge(i["cloud"], "cloud")} '
                      f'<small>{"مطابق للنموذج" if same else "بخلاف النموذج"}</small></div>')
        img2 = (f'<img loading="lazy" src="crops/{esc(i["from_crop"])}" alt="" title="موضع القاعدة">'
                if i.get('from_crop') else '')
        note = notes.get(i['crop']) or notes.get(i.get('from_crop') or '')
        return (f'<figure class="chip{" auto" if i["done"] else ""}" data-id="{cid}"><img loading="lazy" src="crops/{cid}" alt="" title="ما رآه النموذج">{img2}'
                f'<figcaption><div class="word">{esc(i["text"])}</div><div class="where">{esc(where)}</div>'
                f'{verdict}{(ref_badge(i) if tab in ("differs", "add", "maybe") else "")}{raw_line(i)}{status}'
                + (f'<div class="cnote">{esc(note)}</div>' if note else '')
                + f'<div class="others">{others}</div>'
                f'<label class="tick"><input type="checkbox" data-id="{cid}"{" data-auto=1" if i["done"] else ""}> تمّت</label></figcaption></figure>')

    panels, tabbar = [], []
    for k, title, note, f in TABS:
        rows = [i for i in items if f(i)]
        bypage = {}
        for i in rows:
            bypage.setdefault(i['page'], []).append(i)
        order = (sorted(bypage, key=lambda pg: (-max(ref_lean(i) for i in bypage[pg]), pg))
                 if k in ('differs', 'add', 'maybe') else sorted(bypage))
        cards = []
        for pg in order:
            its = sorted(bypage[pg], key=lambda i: _key(i))
            cards.append(
                f'<section class="pg" data-pg="{pg}" data-tab="{k}"><header>'
                f'<div class="pgno"><small>صفحة</small>{pg}</div>'
                f'<div class="cnt">{len(its)} علامة</div>'
                f'<a class="open" target="_blank" rel="noopener" href="{editor_link(pg)}">افتح الصفحة في المحرر ↖</a>'
                f'<label class="tick pgtick"><input type="checkbox" data-id="{k}-pg{pg}"> الصفحة تمّت</label></header>'
                f'<div class="chips">{"".join(chip(i, k) for i in its)}</div></section>')
        nd = sum(1 for i in rows if i['done'])
        count = f'{nd}/{len(rows)}' if k in PRIORITY_TABS else f'{len(rows)}'
        tabbar.append(f'<button role="tab" data-tab="{k}">{esc(title)} <b>{count}</b></button>')
        panels.append(f'<div class="panel" data-panel="{k}" hidden><p class="note">{esc(note)}</p>'
                      f'{"".join(cards) or "<p class=empty>لا شيء هنا.</p>"}</div>')

    page = f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>مراجعة وقوف مصحف {esc(edition)}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Noto+Naskh+Arabic:wght@400;600;700&family=Tajawal:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
    :root{{--bg:#f6f4ee;--fg:#1c1b19;--muted:#6d6a62;--card:#fff;--line:#e2ded2;--accent:#0b6e4f;--accent-soft:#e3f2ec;
    --cv:#0b6e4f;--db:#9a5b00;--warn:#b3261e}}
    @media (prefers-color-scheme:dark){{:root{{--bg:#141412;--fg:#ecebe4;--muted:#a09d94;--card:#201f1c;--line:#34322d;
    --accent:#5fc49b;--accent-soft:#1d2e27;--cv:#5fc49b;--db:#e0a24a;--warn:#f2928b}}}}
    *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 Tajawal,system-ui,sans-serif}}
    .bar{{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 16px 0}}
    .bar .top{{display:flex;flex-wrap:wrap;align-items:center;gap:8px 20px;max-width:1280px;margin:auto}}
    h1{{font-size:20px;margin:0}} .stat{{color:var(--muted);font-size:13px}} .stat b{{color:var(--fg);font-size:15px}}
    .prog{{flex:1;min-width:160px;display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}}
    .prog i{{flex:1;height:8px;border-radius:4px;background:var(--line);overflow:hidden;display:block}}
    .prog i u{{display:block;height:100%;background:var(--accent);width:0;transition:width .2s}}
    .expbtn{{font:inherit;font-size:13px;font-weight:700;background:var(--accent);color:#fff;border:0;border-radius:8px;padding:6px 12px;cursor:pointer}}
    .tools{{display:flex;gap:14px;font-size:13px;color:var(--muted);align-items:center}}
    .tabs{{display:flex;gap:2px;overflow-x:auto;max-width:1280px;margin:8px auto 0}}
    .tabs button{{font:inherit;font-size:14px;border:0;background:none;color:var(--muted);padding:8px 14px;cursor:pointer;
    border-bottom:3px solid transparent;white-space:nowrap}}
    .tabs button b{{background:var(--line);color:var(--fg);border-radius:10px;padding:0 8px;font-size:12px;margin-inline-start:4px}}
    .tabs button[aria-selected=true]{{color:var(--accent);border-color:var(--accent);font-weight:700}}
    main{{max-width:1280px;margin:auto;padding:16px}}
    .note{{color:var(--muted);margin:4px 0 14px;font-size:14px}} .empty{{color:var(--muted)}}
    .panel:not([hidden]){{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:14px;align-items:start}}
    .panel>.note,.panel>.empty{{grid-column:1/-1;margin:0}}
    .pg{{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;scroll-margin-top:110px}}
    .pg.cur{{outline:2px solid var(--accent)}}
    .pg header{{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;padding:10px 14px;border-bottom:1px solid var(--line);background:var(--accent-soft)}}
    .pgno{{font-size:26px;font-weight:700;line-height:1;color:var(--accent)}} .pgno small{{font-size:12px;color:var(--muted);display:block;font-weight:400}}
    .cnt{{color:var(--muted);font-size:14px}}
    .open{{margin-inline-start:auto;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;font-size:14px;padding:7px 14px;border-radius:8px}}
    .open:hover{{filter:brightness(1.1)}}
    .tick{{display:inline-flex;gap:6px;align-items:center;font-size:13px;color:var(--muted);cursor:pointer}}
    .tick input{{width:18px;height:18px;accent-color:var(--accent)}}
    .chips{{display:grid;grid-template-columns:1fr;gap:12px;padding:12px}}
    .pg:has(.chip:nth-child(2)){{grid-column:span 2}} .pg:has(.chip:nth-child(2)) .chips{{grid-template-columns:repeat(auto-fill,minmax(330px,1fr))}}
    .chip{{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:var(--bg)}}
    .chip img{{width:100%;display:block;background:#fff;cursor:zoom-in;aspect-ratio:340/140;object-fit:cover}}
    .chip figcaption{{padding:8px 12px 10px}}
    .word{{font:600 22px/1.4 'Noto Naskh Arabic',serif}} .where{{font-size:12px;color:var(--muted)}}
    .verdict{{display:flex;align-items:center;gap:8px;margin:6px 0;font-weight:500}} .verdict small{{color:var(--muted);margin-inline-start:auto;font-weight:400}}
    .sym{{display:inline-flex;min-width:34px;height:30px;padding:0 8px;align-items:center;justify-content:center;border-radius:8px;
    font:700 18px 'Noto Naskh Arabic',serif;border:2px solid var(--line)}}
    .sym.cv{{border-color:var(--cv);color:var(--cv)}} .sym.db{{border-color:var(--db);color:var(--db)}} .sym.none{{color:var(--muted)}}
    .geo{{font-size:12.5px;border-radius:8px;padding:3px 8px;margin:4px 0;background:var(--accent-soft);color:var(--accent)}}
    .geo.diff{{background:#fde8e6;color:#9c2b20}} .geo small{{opacity:.8;margin-inline-start:6px}}
    @media (prefers-color-scheme:dark){{.geo.diff{{background:#3b1d1a;color:#f2a29a}}}}
    .ref{{font-size:12.5px;border-radius:8px;padding:3px 8px;margin:4px 0}} .ref small{{opacity:.8}}
    .ref.img{{background:#fff3d6;color:#8a5a00}} .ref.db{{background:#e8f4ee;color:#1f6b46}}
    @media (prefers-color-scheme:dark){{.ref.img{{background:#3a2e12;color:#e0a24a}}.ref.db{{background:#16291f;color:#7fcfa3}}}}
    .cnote{{font-size:13px;background:#eef3ff;color:#1d3d8f;border-radius:8px;padding:4px 8px;margin:4px 0}}
    @media (prefers-color-scheme:dark){{.cnote{{background:#1b2540;color:#a9c0ff}}}}
    .others{{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}}
    .oth{{font-size:12px;border:1px solid var(--line);border-radius:6px;padding:0 6px;color:var(--muted)}}
    .oth i{{font-style:normal;margin-inline-end:4px;opacity:.8}}
    .stat-done{{display:flex;align-items:center;gap:8px;font-size:13px;margin:2px 0 6px;padding:4px 8px;border-radius:8px;background:var(--accent-soft);color:var(--accent)}}
    .stat-done.diff{{background:#fff3d6;color:#8a5a00}} .stat-done.pend{{background:#fff0c2;color:#7a4b00;font-weight:600;border:1px solid #e8c15a}} .stat-done small{{margin-inline-start:auto}}
    .sym.cloud{{border-color:currentColor;min-width:28px;height:24px;font-size:15px}}
    @media (prefers-color-scheme:dark){{.stat-done.diff,.stat-done.pend{{background:#3a2e12;color:#e0a24a;border-color:#6b5320}}}}
    .chip:has(input:checked),.pg:has(.pgtick input:checked) .chips{{opacity:.35}}
    .pg:has(.pgtick input:checked) header{{opacity:.6}}
    body.hide-done .pg:has(.pgtick input:checked),body.hide-done .chip:has(input:checked){{display:none}}
    #lb{{position:fixed;inset:0;background:#000d;display:none;align-items:center;justify-content:center;z-index:20;cursor:zoom-out}}
    #lb img{{max-width:94vw;max-height:90vh;image-rendering:auto;background:#fff;border-radius:8px}} #lb.on{{display:flex}}
    kbd{{background:var(--line);border-radius:4px;padding:0 5px;font:12px monospace}}
    @media (max-width:760px){{.pg:has(.chip:nth-child(2)){{grid-column:auto}}.open{{margin-inline-start:0}}}}
    </style></head><body>
    <div class="bar"><div class="top">
    <h1>مراجعة وقوف مصحف {esc(edition)} <small style="font-size:13px;color:var(--muted)">{esc(stamp)}</small></h1>
    <a class="open" href="{IN_EDITOR_REVIEW}?edition={quote(edition)}">راجِع واحفظ في السحابة ↖</a>
    <span class="stat"><b>{tot['match']:,}</b> مطابقة · <b>{tot['wrong']}</b> رمز مختلف · <b>{tot['missing']}</b> لم تُكتشف ·
    <b>{db_total and tot['match'] / db_total:.1%}</b> دقة مطابقة الرمز ·
    <b>{sum(1 for i in items if i.get('pending'))}</b> مسودة بانتظار النشر</span>
    <span class="prog"><i><u id="bar"></u></i><span id="ptxt"></span></span>
    <span class="tools"><button id="exp" type="button" class="expbtn">⬇ تنزيل نتائج المراجعة</button><label class="tick"><input type="checkbox" id="hide"> إخفاء ما تمّ</label>
    <span>اختصارات: <kbd>J</kbd>/<kbd>K</kbd> تنقّل · <kbd>X</kbd> تمّت · <kbd>Enter</kbd> افتح المحرر</span></span>
    </div><nav class="tabs" role="tablist">{''.join(tabbar)}</nav></div>
    <main>{''.join(panels)}</main>
    <div id="lb"><img alt=""></div>
    <script>
    const KEY='book_review_done_{spec_id}', TAB='book_review_tab_{spec_id}';
    let done={{}};try{{done=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}
    const save=()=>{{try{{localStorage.setItem(KEY,JSON.stringify(done))}}catch(e){{}}}};
    let cur=-1;
    const $$=(s,r=document)=>[...r.querySelectorAll(s)];
    function progress(){{
      const p=$$('.panel:not([hidden]) .pg'); const d=p.filter(x=>x.querySelector('.pgtick input').checked).length;
      document.getElementById('bar').style.width=(p.length?100*d/p.length:0)+'%';
      document.getElementById('ptxt').textContent=d+' / '+p.length+' صفحة';
    }}
    $$('input[data-id]').forEach(c=>{{
      c.checked=!!done[c.dataset.id]||c.hasAttribute('data-auto');
      c.addEventListener('change',()=>{{
        done[c.dataset.id]=c.checked;
        if(c.closest('.pgtick')){{ $$('.chip input',c.closest('.pg')).forEach(x=>{{x.checked=c.checked;done[x.dataset.id]=c.checked}}); }}
        else{{ const pg=c.closest('.pg'), all=$$('.chip input',pg), t=pg.querySelector('.pgtick input');
          t.checked=all.every(x=>x.checked); done[t.dataset.id]=t.checked; }}
        save();progress();
      }});
    }});
    $$('.pg').forEach(pg=>{{const all=$$('.chip input',pg),t=pg.querySelector('.pgtick input');
      if(all.length&&all.every(x=>x.checked))t.checked=true;}});
    function show(t){{
      $$('.panel').forEach(p=>p.hidden=p.dataset.panel!==t);
      $$('.tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===t));
      try{{localStorage.setItem(TAB,t)}}catch(e){{}} cur=-1;progress();
    }}
    $$('.tabs button').forEach(b=>b.addEventListener('click',()=>show(b.dataset.tab)));
    let t0='shift';try{{t0=localStorage.getItem(TAB)||'differs'}}catch(e){{}} show(t0);
    document.getElementById('hide').addEventListener('change',e=>document.body.classList.toggle('hide-done',e.target.checked));
    const vis=()=>$$('.panel:not([hidden]) .pg').filter(x=>x.offsetParent!==null);
    function go(n){{const v=vis();if(!v.length)return;cur=Math.max(0,Math.min(v.length-1,n));
      $$('.pg.cur').forEach(x=>x.classList.remove('cur'));v[cur].classList.add('cur');v[cur].scrollIntoView({{block:'start',behavior:'smooth'}});}}
    addEventListener('keydown',e=>{{
      if(e.target.tagName==='INPUT'&&e.target.type!=='checkbox')return;
      const k=e.key.toLowerCase();
      if(k==='j')go(cur+1);else if(k==='k')go(cur-1);
      else if(k==='x'&&cur>=0){{const c=vis()[cur].querySelector('.pgtick input');c.checked=!c.checked;c.dispatchEvent(new Event('change'));go(cur+1);}}
      else if(k==='enter'&&cur>=0){{window.open(vis()[cur].querySelector('.open').href,'_blank');}}
    }});
    document.getElementById('exp').addEventListener('click',()=>{{
      const out={{}};
      $$('.panel').forEach(p=>{{const tab=p.dataset.panel;out[tab]={{}};
        $$('.chip',p).forEach(c=>{{out[tab][c.dataset.id]=c.querySelector('input').checked;}});}});
      const blob=new Blob([JSON.stringify({{exported:new Date().toISOString(),meaning:'checked = reviewer says the model is correct',tabs:out}},null,1)],{{type:'application/json'}});
      const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='{spec_id}_review_ticks.json';a.click();
    }});
    const lb=document.getElementById('lb');
    document.addEventListener('click',e=>{{ if(e.target.matches('.chip img')){{lb.querySelector('img').src=e.target.src;lb.classList.add('on');}}
      else if(lb.contains(e.target)||e.target===lb)lb.classList.remove('on'); }});
    </script></body></html>"""
    (out_dir / 'review.html').write_text(page)
    return summary


def main(argv: list[str] | None = None) -> int:
    import argparse

    from pipeline.cv_waqf.book_audit import default_out

    p = argparse.ArgumentParser(prog='python -m pipeline.cv_waqf book-review')
    p.add_argument('--edition', required=True, choices=list(EDITIONS))
    p.add_argument('--dir', type=Path)
    args = p.parse_args(argv)
    summary = build(args.edition, args.dir or default_out(args.edition))
    print(json.dumps(summary['tabs'], ensure_ascii=False))
    print(f'review in the editor: {IN_EDITOR_REVIEW}?edition={quote(args.edition)}')
    return 0
