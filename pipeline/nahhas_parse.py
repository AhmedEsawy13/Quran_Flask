"""القطع والائتناف (النحاس): rulings and whose they are.

The book lists rulings in running chains over «{quote}» citations:

    {A} قطع كاف وكذا {B} والتمام {C}، قال أبو حاتم {D} كاف وعند غيره تام

Grades come after a quote («قطع كاف»، «تم»، «فإنه تمام»، «فهذا الكافي من
الوقف») or before it («والتمام {X}»، «والكافي بعده {X}»، «ومن التمام {X}»);
«وكذا / وكذلك / ومثله / وبعده» carry the previous grade on; «ليس بقطع كاف»
and «ليس بتمام» are not rulings. «ثم القطع على رؤوس الآيات كاف إلى {X}»
grades every verse end up to X.

Much of the book is other scholars' verdicts: «قال أبو حاتم …» (to the end of
the sentence), «{X} كاف عند أبي حاتم»، «وعن نافع {X} تم»، «ومذهب أحمد بن موسى
أن التمام {X}»، «وعند غيره تام». النحاس speaks of himself as «أبو جعفر»; an
unlabelled ruling is his own.

parse(text) → [Ruling]; seat(...) places each quote on a Hafs word.
"""
import re
from dataclasses import dataclass, field

SELF = 'أبو جعفر'
SELF_MARK = '__self__'

_G = {'تام': 'تام', 'تمام': 'تام', 'التام': 'تام', 'التمام': 'تام',
      'كاف': 'كاف', 'كافٍ': 'كاف', 'الكافي': 'كاف', 'كافي': 'كاف',
      'حسن': 'حسن', 'الحسن': 'حسن', 'صالح': 'صالح', 'الصالح': 'صالح'}
_GW = r'(تمام|تام|كافٍ|كاف|كافي|حسن|صالح)'

# grade right after «}»
_AFTER = [
    (re.compile(r'^(?:هو\s+)?(?:(?:قطع|وقف|القطع|الوقف)\s+)?' + _GW + r'(?![ء-ي])'), 1),
    (re.compile(r'^(?:ف?إنه|فهو|وهو)\s+(?:(?:قطع|وقف)\s+)?' + _GW + r'(?![ء-ي])'), 1),
    (re.compile(r'^و?ف?هذا\s+(?:هو\s+)?(?:(?:القطع|الوقف|قطع|وقف)\s+)?'
                r'(التمام|التام|الكافي|الحسن|الصالح|تمام|تام|كاف|حسن|صالح)(?![ء-ي])'), 1),
    # «تم القطع على رؤوس الآيات» is a miscopied «ثم»
    (re.compile(r'^تم(?:\s+الكلام)?(?![ء-ي])(?!\s+(?:القطع|الوقف|الوقوف|التمام|على))'), None),
    (re.compile(r'^(?:عن|وعن)\s+نافع\s+تم(?![ء-ي])'), None),
]
# «ليس بقطع كاف»، «ليس بتمام»، «لا يكفي»: no ruling; «ليس بوقف» alone: لا
_NEG = re.compile(r'^(?:و?ليس|ولا|لا|غير)\s+(?:ب(?:قطع|وقف|تمام|تام|كاف|حسن|صالح)|يكفي|يتم|يوقف|يقف|تمام|تام|كاف)')
_NOSTOP = re.compile(r'^(?:و?ليس\s+بوقف|ليس\s+بموضع\s+قطع|لا\s+يوقف\s+عليه)(?!\s+(?:كاف|تام|حسن|صالح))')

# grade right before «{»
_BEFORE = re.compile(
    r'(?:^|[\s،:؛.])(?:و|ف)?(?:(?:القطع|الوقف|الوقوف)\s+)?'
    r'(التمام|التام|الكافي|الحسن|الصالح|أتم منه|أتم منهما|أكفى منه|أحسن منه)'
    r'(?:\s+أيضا)?(?:\s+(?:بعده|بعد\s+هذا|فيه))?(?:\s+(?:عنده|عندهما|عند\s+[^{}.،]{2,30}?|على\s+قول\s+[^{}.،]{2,30}?))?'
    r'\s*:?\s*$')
_FROM_TAIL = re.compile(r'(?:ومن|من)\s+(التمام|الكافي|الحسن|الوقف\s+التام|الوقف\s+الكافي|الوقف\s+الحسن)\s*:?\s*$')
_BEFORE_MAP = {'أتم منه': 'تام', 'أتم منهما': 'تام', 'أكفى منه': 'كاف', 'أحسن منه': 'حسن'}

_CHAIN = re.compile(r'(?:^|[\s،])(?:و|ثم\s+)?(?:كذا|كذلك|مثله|بعده)(?:\s+(عنده|عند\s+[^{}.،]{2,30}?))?\s*[:،]?\s*$')

# «ثم القطع على رؤوس الآيات كاف إلى {X}»، «رؤوس الآي حسن إلى {X}»
_BLANKET = re.compile(r'رؤوس\s+(?:الآيات|الآي|الآية)\s+(?:(?:قطع|وقف)\s+)?' + _GW + r'\s+(?:إلى|حتى)\s*(?:قوله)?\s*(?:جل\s+وعز)?\s*$')

_NAME = r'([^{}:.،؛]{2,40}?)'
_SPEAKER = re.compile(r'(?:^|[\s،.])(?:و|ثم\s+)?قالت?\s*:?\s+' + _NAME + r'\s*(?::|(?=[\s،]*\{)|(?=\s+ومن\s)|(?=\s+والتمام)|(?=\s+التمام)|(?=\s+الوقف))')
_SPEAKER_AFTER = re.compile(r'(?:^|[\s،.])(?:وخالفه\s+|و)?' + _NAME + r'\s+قال\s*:')
_NAFI_MENTION = re.compile(r'(?:^|[\s،.])(?:و?عن|روى\s+عن|روي\s+عن|روينا\s+عن)\s+نافع')
_ANON_SPEAKER = re.compile(r'(?:^|[\s،])(?:و|ثم\s+)?قال\s*:?\s*(?:و?(?:ال)?(?:وقف|قطع)?\s*(?:ال)?(?:تمام|كافي|حسن|تام)?\s*(?:بعده)?\s*)?$')
_AT = re.compile(r'^[\s،]*(?:عند|على\s+قول|في\s+قول|على\s+مذهب|وهو\s+قول|وهو\s+مذهب|قول)\s+' + _NAME +
                 r'(?=\s*(?:$|[،.{]|و(?:ال|عند|هو|كذا|قال|عن|غلط|خولف|ليس|أبو|أحمد)|\s+(?:وغلط|وخولف|لأن|إن|إذا|ثم|فأما|والتمام|والكافي)))')
_NAFI_BEFORE = re.compile(r'(?:و?عن|روي?\s+عن|روينا\s+عن|وروى\s+[^{}.،]{2,30}\s+عن)\s+نافع\s*:?\s*$')
_NAFI_THAT = re.compile(r'(?:و?عن|روي?\s+عن|روينا\s+عن)\s+نافع\s+(?:أن|إن)\s+(التمام|التام|الكافي)\s*:?\s*$')
_SAYS_THAT = re.compile(r'(?:^|[\s،.])و?' + _NAME + r'\s+(?:يقول|يقولون|يذهب\s+إلى|يذهبون\s+إلى)\s+(?:أن\s+)?'
                        r'(التمام|التام|الكافي|الحسن)\s*:?\s*$')
_MADHHAB = re.compile(r'(?:و?مذهب|و?زعم|و?ذكر|و?اختار|و?اختيار|و?قول)\s+' + _NAME + r'\s+(?:أن|إن)\s+(?:ال)?(?:وقف\s+)?(التمام|التام|الكافي|الحسن|الصالح)\s*(?:عنده)?\s*:?\s*$')
_OTHER_BEFORE = re.compile(r'(?:وقال\s+غيره|وعند\s+غيره|عند\s+غيره)\s+(?:ال)?(التمام|التام|الكافي|الحسن)\s*$|'
                           r'(?:و)?(?:ال)?(التمام|الكافي|الحسن)\s+عند\s+غيره(?:ما|هم)?\s*$')
# second opinion on the same quote: «وعند غيره تام»، «وهو عند غيره كاف»، «وأبو حاتم يذهب إلى أنه كاف»
_SECOND = re.compile(r'(?:و(?:هو\s+)?عند\s+' + _NAME + r'|و' + _NAME + r'\s+يذهب\s+إلى\s+أنه|وقال\s+' + _NAME + r'\s*:?)\s+'
                     r'(?:(?:قطع|وقف)\s+)?' + _GW + r'(?![ء-ي])')
# «{X} قال الأخفش: هذا التمام»، «{X} قال أبو حاتم: كاف»
_SAID_AFTER = re.compile(r'^(?:و)?قالت?\s+' + _NAME + r'\s*:\s*(?:هذا\s+|هو\s+)?(?:(?:قطع|وقف|القطع|الوقف)\s+)?'
                         r'(التمام|تمام|تام|الكافي|كافٍ|كاف|حسن|صالح)(?![ء-ي])')
_READING = re.compile(r'قراءة|قرأ|يقرأ|يقرؤ')

# waqf authorities the book cites, with the spellings it uses
_WAQF = {
    'أبو حاتم': ('أبو حاتم', 'أبي حاتم', 'ابو حاتم', 'ابي حاتم', 'أبو خاتم', 'أبو اتم'),
    'الأخفش': ('الأخفش',), 'نافع': ('نافع',), 'يعقوب': ('يعقوب',),
    'أحمد بن موسى': ('أحمد بن موسى',), 'محمد بن عيسى': ('محمد بن عيسى',),
    'أحمد بن جعفر': ('أحمد بن جعفر',), 'أبو عبد الله': ('أبو عبد الله', 'أبي عبد الله', 'أبو عبيد الله'),
    'العباس بن الفضل': ('العباس بن الفضل', 'عباس بن الفضل', 'العباس'), 'نصير': ('نصير',),
    'القتبي': ('القتبي', 'القتيبي', 'عبد الله بن مسلم'), 'الفراء': ('الفراء',),
    'الكسائي': ('الكسائي',), 'أبو عبيد': ('أبو عبيد', 'أبي عبيد'), 'ابن كيسان': ('ابن كيسان',),
    'أبو إسحاق': ('أبو إسحاق', 'أبي إسحاق'), 'محمد بن سعدان': ('محمد بن سعدان',),
    'ابن شاذان': ('ابن شاذان',), 'سيبويه': ('سيبويه',), 'محمد بن يزيد': ('محمد بن يزيد',),
    'المازني': ('المازني',), 'النضر بن شميل': ('النضر بن شميل',),
    'أبو عمرو بن العلاء': ('أبو عمرو بن العلاء', 'أبي عمرو بن العلاء'),
    'عيسى بن عمر': ('عيسى بن عمر',), 'محمد بن جرير': ('محمد بن جرير',),
    'علي بن سليمان': ('علي بن سليمان', 'على بن سليمان'), 'محمد بن إسحاق': ('محمد بن إسحاق',),
}
_OTHERS = re.compile(r'^(?:غير|آخر|بعض\s|أكثر\s|الجماعة|أهل\s|جماعة)')
# «قال» that introduces Allah's words or a tafsir authority, not a waqf verdict
_BREAK = re.compile(r'^(?:جل|الله|تعالى|قتادة|مجاهد|الحسن|الضحاك|ابن عمر|ابن عباس|سعيد بن جبير|السدي|'
                    r'ابن زيد|زيد بن أسلم|ابن جري|محمد بن سيرين|أبو سعيد|أبو مالك|عطية|عكرمة|'
                    r'محمد بن جعفر بن الزبير|رسول الله|النبي|أبو هريرة|عائشة|ابن مسعود|الربيع|عامر)')
BREAK = '__break__'


def name(raw, strict=False):
    """Canonical scholar; None when unrecognised; BREAK for Allah / tafsir
    authorities; SELF_MARK for النحاس himself. `strict`: the whole text must
    be the name (or «NAME وNAME»), as after «قال»."""
    if raw is None:
        return None
    n = re.sub(r'\s+', ' ', raw).strip(' :،')
    n = re.sub(r'^(?:الشيخ|الإمام|عند)\s+', '', n)
    if n.startswith(('أبو جعفر', 'أبي جعفر', 'ابو جعفر', 'أبو جفعر')):
        return SELF_MARK
    if _BREAK.match(n):
        return BREAK
    first = re.split(r'\s+و(?=[ء-ي])', n)[0] if strict else n
    if re.fullmatch(r'(?:غيره|غيرهما|غيرهم|غير\s+\S+|آخرون|بعضهم|بعض\s+\S+(?:\s+\S+)?|أكثر\s+\S+(?:\s+\S+)?|'
                    r'الجماعة|جماعة|أهل\s+\S+)', first) or (not strict and _OTHERS.match(n)):
        return 'غيره'
    for canon, forms in _WAQF.items():
        for f in forms:
            if first == f or (not strict and (n.startswith(f + ' ') or n.startswith(f + ':'))):
                return canon
    return None


@dataclass
class Ruling:
    start: int
    end: int
    quote: str
    grade: str
    by: str = None                 # scholar; None = النحاس
    how: str = ''                  # after / before / chain / second / blanket
    reading: bool = False          # tied to a reading («على قراءة من قرأ …»)
    blanket_to: int = None         # for blanket rows: index of the {X} quote
    prev_quote: str = None         # for blanket rows: the quote before the statement
    note: str = ''


def _speaker(text, pos, prev_end=0):
    """Scholar whose words the quote at `pos` is: a «قال NAME» between the
    previous quote and this one that introduces it directly («قال أبو حاتم
    {X}»، «قال يعقوب: ومن الوقف {X}»، «وخالفه أحمد بن جعفر قال: التمام {X}»),
    not one followed by prose of its own («وقال نصير: أكره أن أقف … {X}»).
    A bare «قال» continues the sentence's last named speaker («قال أبو حاتم
    {A} كاف، قال والتمام {B}»، «عن نافع قال {A} تم قال {B} تم»). Unlabelled
    items in a list are النحاس's own even after someone else was quoted."""
    gap = text[prev_end:pos + 1]
    named = None
    for rx_ in (_SPEAKER, _SPEAKER_AFTER):
        for m in rx_.finditer(gap):
            rest = gap[m.end():].strip(' :،{')
            if len(rest) > 30:
                continue
            named = name(m.group(1), strict=True) or named
    if named in (BREAK, SELF_MARK):
        return None
    if named:
        return named
    if _ANON_SPEAKER.search(text[prev_end:pos]):
        st = max(text.rfind('.', 0, pos), text.rfind('\n', 0, pos)) + 1
        marks = [(m.start(), name(m.group(1), strict=True)) for m in _SPEAKER.finditer(text[st:prev_end])]
        marks += [(m.start(), 'نافع') for m in _NAFI_MENTION.finditer(text[st:prev_end])]
        who = None
        for _, n in sorted(marks):
            who = None if n in (BREAK, SELF_MARK) else (n or who)
        return who
    return None


def _clause(text, s, e, lo=0):
    a = max(text.rfind('.', 0, s), text.rfind('\n', 0, s)) + 1
    a = max(a, lo)
    b = text.find('.', e)
    b = b if 0 <= b - e < 220 else e + 160
    seg = text[a:b]
    if seg.count('{') > seg.count('}'):
        seg = seg[:seg.rfind('{')]            # don't end inside the next quote
    return re.sub(r'\s+', ' ', seg).strip(' ،')


def parse(text):
    text = re.sub(r'[ \t]+', ' ', text)
    quotes = [(m.start(), m.end(), m.group(1)) for m in re.finditer(r'\{([^{}]{1,200})\}', text)]
    out = []
    grades = [None] * len(quotes)      # own resolved grade per quote (for chains)
    bys = [None] * len(quotes)
    for i, (s, e, q) in enumerate(quotes):
        nxt = quotes[i + 1][0] if i + 1 < len(quotes) else len(text)
        prv = quotes[i - 1][1] if i else 0
        prv_s = quotes[i - 1][0] if i else 0
        after = text[e:nxt].lstrip(' ،')
        before = text[prv:s].rstrip()
        reading = bool(_READING.search(text[max(prv, s - 120):s]) or
                       re.search(r'على\s+قراءة|قراءة\s+من|من\s+قرأ', text[e:min(nxt, e + 90)]))
        g = by = None
        how = ''
        tail = ''
        if _NOSTOP.match(after):
            g, how = 'لا', 'after'
        elif _NEG.match(after):
            grades[i] = 'NEG'
            continue
        else:
            for rx_, grp in _AFTER:
                m = rx_.match(after)
                if m:
                    g = _G[m.group(grp)] if grp else 'تام'
                    if 'نافع' in m.group(0):
                        by = 'نافع'
                    how, tail = 'after', after[m.end():]
                    break
        if g is None:
            m = _SAID_AFTER.match(after)
            if m:
                g, how, by, tail = _G[m.group(2)], 'after', name(m.group(1)), after[m.end():]
                by = by or SELF_MARK
        if g is None:
            m = _BEFORE.search(before)
            if m and m.group(1) in ('الحسن', 'التمام', 'الكافي') and \
                    re.search(r'(?:قال|وقال|عن|روى|وروى|قول|مذهب)\s+(?:ال)?$', before[:m.start(1)].rstrip() + ' '):
                m = None
            if m:
                word = m.group(1)
                g = _BEFORE_MAP.get(word) or _G[word]
                how = 'before'
                at = re.search(r'عند\s+([^{}.،]{2,30}?)\s*:?\s*$', m.group(0))
                if at:
                    by = name(at.group(1))
                elif re.search(r'عنده(?:ما|م)?\s*:?\s*$', m.group(0)):
                    # «والتمام عندهما {X}»: the scholars just named («عند الأخفش وأبي حاتم»)
                    by = bys[i - 1] if i and bys[i - 1] else None
                    if by is None:
                        near = [name(x.group(1)) for x in
                                re.finditer(r'عند\s+([^{}.،]{2,40}?)(?=\s+(?:و?التمام|لأن)|\s*[{،.])', text[max(0, s - 300):s])]
                        near = [n for n in near if n not in (None, BREAK, SELF_MARK)]
                        by = near[-1] if near else None
                elif re.search(r'على\s+قول\s+', m.group(0)):
                    by = name(re.search(r'على\s+قول\s+([^{}.،]{2,30}?)\s*:?\s*$', m.group(0)).group(1))
            else:
                m = _FROM_TAIL.search(before)
                if m and _AFTER_FROMWAQF.match(after):
                    pass                                  # «ومن الوقف {X} فهذا الكافي» handled by after
                elif m:
                    g, how = _G[m.group(1).split()[-1]], 'before'
        m = _NAFI_THAT.search(before)
        if m and how in ('', 'before'):
            g, how, by = _G[m.group(1)], 'before', 'نافع'
        m = _SAYS_THAT.search(before)
        if m and how in ('', 'before') and name(m.group(1)) not in (None, BREAK, SELF_MARK):
            g, how, by = _G[m.group(2)], 'before', name(m.group(1))
        m = _MADHHAB.search(before)
        if m and how in ('', 'before'):
            g, how, by = _G[m.group(2)], 'before', name(m.group(1)) or by
        m = _OTHER_BEFORE.search(before)
        if m and how in ('', 'before'):
            g, how, by = _G[m.group(1) or m.group(2)], 'before', 'غيره'
        if g is None:
            m = _CHAIN.search(before)
            if m and i and grades[i - 1] not in (None, 'NEG'):
                g, how = grades[i - 1], 'chain'
                if m.group(1):
                    by = bys[i - 1] if m.group(1) == 'عنده' else name(m.group(1)[4:])
                elif re.search(r'بعده\s*[:،]?\s*$', before):
                    by = None
                else:
                    by = bys[i - 1]
        if g is None:
            # «{A} وكذا {B} قطع كاف»: B's grade reaches back to A
            continue
        if how == 'after' and by is None:
            m = _AT.match(tail)
            if m:
                by = name(m.group(1))
        if by is None and _NAFI_BEFORE.search(before):
            by = 'نافع'
        if by is None and how != 'chain':
            by = _speaker(text, s, prv)
        if by in (SELF_MARK, BREAK):
            by = None
        grades[i], bys[i] = g, by
        out.append(Ruling(s, e, q, g, by, how, reading, note=_clause(text, s, e, prv_s)))
        if how == 'after':
            m = _BEFORE.search(before)
            at = m and re.search(r'عند\s+([^{}.،]{2,30}?)\s*:?\s*$', m.group(0))
            if at:
                w2 = name(at.group(1))
                g2 = _BEFORE_MAP.get(m.group(1)) or _G[m.group(1)]
                if w2 not in (None, BREAK, SELF_MARK) and (g2, w2) != (g, by):
                    out.append(Ruling(s, e, q, g2, w2, 'second', reading, note=_clause(text, s, e, prv_s)))
        # a second view on the same quote
        m = _SECOND.search(tail[:80]) if how == 'after' else None
        if m:
            who = name(m.group(1) or m.group(2) or m.group(3))
            who = None if who in (SELF_MARK, BREAK) else who
            g2 = _G[m.group(4)]
            if g2 != g:
                if who:
                    out.append(Ruling(s, e, q, g2, who, 'second', reading, note=_clause(text, s, e, prv_s)))
    # back-propagate «{A} وكذا {B} grade» to A
    for i in range(len(quotes) - 1, 0, -1):
        if grades[i - 1] is None and grades[i] not in (None, 'NEG'):
            between = text[quotes[i - 1][1]:quotes[i][0]].strip(' ،')
            if re.fullmatch(r'(?:و?كذا|و?كذلك|و|،)', between):
                s, e, q = quotes[i - 1]
                grades[i - 1], bys[i - 1] = grades[i], bys[i]
                out.append(Ruling(s, e, q, grades[i], bys[i], 'chain-back',
                                  bool(_READING.search(text[max(0, s - 120):s])),
                                  note=_clause(text, s, e, quotes[i - 2][0] if i >= 2 else 0)))
    # blanket «رؤوس الآيات كاف إلى {X}»
    for i, (s, e, q) in enumerate(quotes):
        prv = quotes[i - 1][1] if i else 0
        m = _BLANKET.search(text[prv:s])
        if m:
            out.append(Ruling(s, e, q, _G[m.group(1)], None, 'blanket', blanket_to=i,
                              prev_quote=quotes[i - 1][2] if i else None,
                              note=_clause(text, prv + m.start(), e, quotes[i - 1][0] if i else 0)))
    out.sort(key=lambda r: (r.start, r.how == 'second'))
    return out


_AFTER_FROMWAQF = re.compile(r'^ف?هذا\s+(?:هو\s+)?(?:(?:القطع|الوقف)\s+)?(التمام|التام|الكافي|الحسن|الصالح)')


# ── seating ───────────────────────────────────────────────────────────────
def occurrences(stream, qwords, match_word, level=1):
    """End indices in `stream` where the whole quote matches."""
    k = len(qwords)
    out = []
    for i in range(0, len(stream) - k + 1):
        if all(match_word(qwords[j], stream[i + j][2], level) for j in range(k)):
            out.append(i + k - 1)
    return out


def seat(stream, cursor, qwords, match_word, back=40, jump=600):
    """(index, confident) for the quote nearest-forward from `cursor`. A
    quote ending on the word the cursor sits on (a refrain like «فبأي آلاء
    ربكما تكذبان») moves strictly forward."""
    if not qwords:
        return None, False
    cands = occurrences(stream, qwords, match_word, 1) or occurrences(stream, qwords, match_word, 2)
    if not cands:
        return None, False
    strict = cursor > 0 and match_word(qwords[-1], stream[cursor][2], 1)
    near = [c for c in cands if (c > cursor if strict else c >= cursor - back)]
    if near:
        # nearest, with backward distance weighed 3× (the book moves forward)
        best = min(near, key=lambda c: (c - cursor) if c >= cursor else (cursor - c) * 3)
        return best, (len(cands) == 1 or abs(best - cursor) <= jump)
    return cands[-1], len(cands) == 1
