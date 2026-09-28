"""العلّة of a classical waqf ruling, separated from the book text around it.

A row's `note` is the stretch of book text beside its quote, so it may hold
the reason («لأن ما بعده متعلق به»), but also chain wording («ومثله»,
«وكذا {X}»), the NEXT quote's ruling («{ونقدس لك} [كاف]»), an isnad
(«حدثنا …»), or nothing useful («وقد ذكر»). `illa(note, quote)` keeps only
the reason for THIS quote; `is_chain` says whether the ruling is inherited
(«ومثله / وكذا / وكذلك …»), so the caller can name the ruling it follows.
"""
import re

_TASHKEEL = re.compile(r'[ؐ-ًؚ-ٰٟۖ-ۭـ]')
_OPEN, _CLOSE = '{(«[', '})»]'
_QUOTE = r'(?:\{[^{}]{1,200}\}|\([^()]{1,160}\)|«[^«»]{1,160}»)'
_REF = r'(?:\s*\[(?:في\s+الآية\s+)?[\d،, ي-]{1,12}\]|\s*\(\d{1,3}\))*'   # «[151]»، «(24)»، «[في الآية 49]»
_GRADE = (r'(?:(?:ف?هذا|فإنه|وهو|هو)\s+(?:هو\s+)?)?(?:(?:وقف|قطع|الوقف|القطع)\s+)?(?:\[)?(?:تام|تمام|التمام|كاف|كافٍ|الكافي|حسن|الحسن|'
          r'صالح|جائز|مفهوم|قبيح|أتم منه|أحسن منه|أكفى منه|تم الكلام|تم)(?:\])?(?![ء-ي])')
_CHAIN = r'(?:و?مثله|و?مثلها|و?مثلهما|و?كذا|و?كذلك|و?نحوه|ونظيره|و?بعده)'
_SPEAKER = r'(?:عند|على\s+قول|في\s+قول|عن)\s+[^{}()«».،:]{2,40}?'

# where the text stops being about this quote
_STOP = re.compile(
    # «لأنه مثل الوقف على {تأكلون}» compares; it does not open the next item
    r'(?<!مثل)(?:^|[\s،.؛:])(?:' +
    # «وبعده {X}» chains, but «على استئناف ما بعده، «من نشاء» كذلك» does not
    _CHAIN.replace('و?بعده', 'وبعده') + r'\s*(?:عنده\s*)?[:،]?\s*(?:قوله\s*:?\s*)?[{(«]' +   # «وكذا {X}»
    r'|(?:و|ف|ثم\s+)?(?:ال(?:تمام|تام|كافي|حسن|صالح)|(?:ال)?(?:وقف|قطع)\s+(?:ال)?(?:تام|كافي|حسن|صالح))'
    r'(?:\s+(?:أيضا|بعده|عنده|عندهما|فيه|على|عند\s+[^{}()«».،]{2,30}?|على\s+قول\s+[^{}()«».،]{2,30}?))*'
    r'\s*:?\s*[{(«]' +                                                                   # «والتمام بعده عند فلان {X}»
    r'|(?:و|ف)?(?:ال)?وقف\s+على\s*(?:قوله\s*:?\s*)?[{(«]' +                               # «والوقف على (X) تام»
    r'|(?:و|ف)?(?:ال)?(?:تمام|كافي|وقف)\s+(?:بعده\s+)?(?:على\s+ما\s+|عند\s+|على\s+قول\s+)' +                  # «والتمام على ما روى عن نافع …»
    r'|(?<![ء-ي])وعند\s+[^{}()«».]{2,30}?\s*[{(«]' +                                            # «وعند غيرهما {X}»
    r'|(?:و|ف)?(?:ثم|تم)\s+(?:القطع|الوقف|الوقوف)|ثم\s+آخر\s+السورة|ثم\s+يبتد[ئي]' +      # «ثم القطع على رؤوس الآيات …»
    r'|(?:و?كذلك|و?كذا)?\s*(?:رؤوس\s+الآي|الفواصل)' +                                   # blanket statements about later verses
    r'|(?:و?عن|روى\s+عن|روينا\s+عن)\s+نافع' +
    r'|(?:قال\s*:?\s*)?(?:حدثنا|أخبرنا|حدثني|أخبرني|أنبأنا|ثنا)(?![ء-ي])' +                         # isnad
    r'|' + _QUOTE + _REF + r'\s*[:،]?\s*' + _GRADE +                                    # «{X} كاف»
    r')')
_LEAD = re.compile(r'^[\s،.؛:\-]*(?:' + _REF + r'\s*[:،]?\s*)?(?:' + _GRADE +
                   r'(?:\s*[،,]?\s*' + _SPEAKER + r'(?=[\s،.]|$))?)?(?:\s+(?:الكلام|من\s+الوقف))?[\s،.؛:\-]*')
_EMPTY = re.compile(r'^(?:و?قد\s+ذكر(?:نا)?|و?قد\s+تقدم|وهو|و?قال|وقيل|ثم|إلى|أي|وليس|غير'
                    r'|على\s+ما(?:\s+(?:روينا|روى|روي))?'      # «تام على ما روينا عن نافع»
                    # a speaker or a dangling «والوقف على» is not a reason
                    r'|و?عند\s+[^\s،.]+(?:\s+(?:بن|أبي|و)\s*[^\s،.]+){0,3}'
                    r'|و?(?:[^\s،.]+\s+)?بن\s+[^\s،.]+'
                    r'|و?(?:ال)?(?:قطع|وقف)\s+على'
                    r'|من\s+ذلك|منه)$')                            # «أكفى من ذلك»
# a quote that opens the next item: not introduced by a reasoning word
_REASON_WORDS = {'قوله', 'قول', 'لأن', 'لأنه', 'لأنها', 'أي', 'مثل', 'بعد', 'بعده', 'قبل', 'قبله', 'إلى', 'على',
                 'من', 'في', 'عن', 'هو', 'وهو', 'التقدير', 'والتقدير', 'بمعنى', 'معنى', 'نعت', 'بدل', 'خبر',
                 'و', 'أو', 'يعني', 'يريد', 'كقوله', 'وقوله', 'وكذلك', 'بين', 'دون', 'حتى', 'مع', 'عند',
                 'ب', 'ل', 'فعل', 'اسم', 'تقول', 'قرأ', 'يقرأ', 'قراءة', 'وقرأ', 'ومن', 'فمن', 'لام'}


def _cut_at_next_item(text):
    for m in re.finditer(_QUOTE, text):
        prev = re.findall(r'[ء-ي]+', text[max(0, m.start() - 20):m.start()])
        lead = text[max(0, m.start() - 3):m.start()]
        if m.start() == 0:
            if m.group(0)[0] in '{(':      # a braced quote right after ours is the next item
                return ''
            continue
        if not prev or (prev[-1] not in _REASON_WORDS and not prev[-1].startswith(('ب', 'ل', 'ك'))
                        and re.search(r'[،.}\])»]\s*$|^\s*$', text[:m.start()].rstrip()[-1:] or ' ')):
            return text[:m.start()]
    return text
_RELAY_ONLY = re.compile(r'^(?:و?قال|وروى|وحكى|وزعم|و?عن|روي\s+عن)\s+[^:«({]*$')


def _plain(s):
    return re.sub(r'\s+', ' ', _TASHKEEL.sub('', s or '')).strip()


def _find_quote(text, quote):
    """(start, end) of this row's own bracketed quote in the note, or None."""
    q = _plain(quote)
    if not q:
        return None
    words = [re.escape(w) for w in q.split()]
    pat = r'[{(«]\s*' + r'\s+'.join(words) + r'\s*[})»]'
    m = re.search(pat, text)
    return (m.start(), m.end()) if m else None


_BLANKET = re.compile(r'(?:(?:ثم|تم)\s+)?(?:ال)?(?:قطع|وقف|وقوف)\s+على\s+رؤوس\s+الآ[يا][^{}.]{0,40}\{[^{}]+\}'
                      r'|(?:و?كذا\s+|و?كذلك\s+)?رؤوس\s+الآ[يا][^{}.]{0,40}\{[^{}]+\}')


def split(note, quote='', grade_raw=None):
    """(reason, chain) for one row."""
    text = _plain(note)
    if not text:
        return '', False
    if grade_raw == 'رؤوس الآي':           # a verse end covered by a general statement
        if text.startswith('حكم عام'):
            return text, False
        m = _BLANKET.search(text)
        return ('حكم عام: «' + m.group(0).strip() + '»' if m else 'حكم عام على رؤوس الآي'), False
    if grade_raw == 'آخر السورة':
        return 'التمام آخر السورة', False
    chain = False
    hit = _find_quote(text, quote)
    if hit:
        before, text = text[:hit[0]], text[hit[1]:]
        chain = bool(re.search(_CHAIN + r'\s*(?:عنده\s*)?[:،]?\s*(?:على\s+)?(?:قوله\s*:?\s*)?$', before.rstrip()))
        # «(X)، و (Y)، (Z) حسن»: the other items of the same list
        if re.match(r'^' + _REF + r'\s*،\s*و?\s*[{(«]', text):
            return '', chain
    else:
        m = re.match(r'^' + _CHAIN + r'(?![ء-ي])', text)
        if m:
            chain = True
            text = text[m.end():]
            # «ومثله «X»، «Y»» / «ومثله علينا»: the chain's own list of words
            text = re.sub(r'^\s*[:،]?\s*(?:(?:قوله\s*:?\s*)?' + _QUOTE + _REF + r'\s*[،و]?\s*)+', ' ', text)
    # the note starts inside the next quote («تجري من تحتها الأنهار) [14] [تام]»)
    close = min([i for i in (text.find(c) for c in _CLOSE[:3]) if i >= 0] or [len(text)])
    opens = min([i for i in (text.find(o) for o in _OPEN[:3]) if i >= 0] or [len(text)])
    if close < opens:
        return '', chain
    text = _LEAD.sub('', text, count=1)
    if chain and re.match(r'^\s*(?:رؤوس\s+الآي|الفواصل)', text):
        return '', chain
    # «وكذا رأس الآية التي بعدها»، «مثله فيما يأتي»: about other verses, not this one
    if re.match(r'^\s*(?:و?كذا|و?كذلك|و?مثله)?\s*(?:رأس\s+الآية|رؤوس\s+الآي|فيما\s+يأتي|ما\s+بعده\s+إلى)', text):
        return '', chain
    text = _cut_at_next_item(text)
    m = _STOP.search(text)
    if m:
        text = text[:m.start()]
    # a trailing «… ومثله» / «وكذا» introduces the NEXT item, not this reason
    text = re.sub(r'(?:[\s.،؛]+(?:و|ثم|وليس|وكذا|وكذلك|ومثله|ومثلها|ونظيره|قال|وقال|ف))+\s*[:،]?\s*$', '',
                  text.strip(' ،.؛:-')).strip(' ،.؛:-')
    text = re.sub(r'[\s،.]+و?قال\s+[^\s:،.]{2,}(?:\s+[^\s:،.]+){0,3}$', '', text).strip(' ،.؛:-')   # «… وقال القتبي»
    # never end inside a bracket
    for o, c in zip(_OPEN, _CLOSE):
        if text.count(o) > text.count(c):
            text = text[:text.rfind(o)].strip(' ،.؛:-')
    words = re.findall(r'[ء-ي]{2,}', text)
    if len(words) < 2 or _EMPTY.match(text) or _RELAY_ONLY.match(text):
        return '', chain
    return text, chain


def illa(note, quote='', grade_raw=None):
    return split(note, quote, grade_raw)[0]


_ADDED = {'رؤوس الآي', 'آخر السورة', 'يحسن الوقف', 'لا يحسن الوقف', 'يتم الوقف', 'يكفي الوقف'}


def chain_head(conn, row):
    """The ruling a «ومثله / وكذا» row follows: walk back through the rows
    just before it in book order (seq) while each has the same grade, is at
    most 5 verses back, and is itself a chain item; the first non-chain one
    is the head. Returns (quote, ayah, reason) or None when not certain."""
    cur = dict(row)
    for _ in range(12):
        prev = conn.execute(
            'SELECT id, seq, quote, ayah, note, grade, grade_raw FROM classical WHERE source=? AND surah=? '
            'AND conf=1 AND (seq < ? OR (seq = ? AND id < ?)) ORDER BY seq DESC, id DESC LIMIT 1',
            (row['source'], row['surah'], cur['seq'], cur['seq'], cur['id'])).fetchone()
        if not prev or (row['ayah'] or 0) - (prev[3] or 0) > 5:
            return None
        if prev[6] in _ADDED:                  # rows an audit added (verse ends, آخر السورة …)
            cur = {'id': prev[0], 'seq': prev[1]}
            continue
        if prev[5] != row['grade']:
            return None
        reason, chain = split(prev[4], prev[2], prev[6])
        if not chain:
            return prev[2], prev[3], reason
        cur = {'id': prev[0], 'seq': prev[1]}
    return None


def display(conn, row):
    """{'illa': reason to show, 'follows': 'quote (ayah)' for a chain item}."""
    reason, chain = split(row['note'], row['quote'], row['grade_raw'])
    out = {'illa': reason, 'follows': None}
    if chain:
        head = chain_head(conn, row)
        if head:
            quote, ayah, head_reason = head
            out['follows'] = f'{quote} ({ayah})'
            if not reason:
                out['illa'] = head_reason
    return out
