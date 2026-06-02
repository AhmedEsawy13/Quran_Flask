#!/usr/bin/env python3
"""Rebuild the corrupted ``quran_script.db`` ``words`` table.

Root cause: ``words`` is corrupted (relocated/merged/missing words), while
``mushaf_layout_inferred.db`` is the clean authoritative source for
``word_index -> word`` (its ayah-line ``line_text`` tokens fill each line's
word_index span exactly). ``word_index`` is also the Shemrly glyph key
(glyph = base + word_index - page_first), so a wrong word_index draws the wrong
glyph — fixing ``words`` to match layout fixes those visual bugs.

Strategy:
  * layout flat sequence  -> ground truth for ``word_index`` (physical order)
  * QPC Hafs flat sequence -> ground truth for verse identity (surah:ayah:pos) + text
  * align the two by letter-skeleton (difflib); 99.74% align 1:1.
  * resolve the handful of structured exceptions (tatweel/sajda variants,
    fused word+number tokens, displaced identical blocks = moves).

Writes a NEW sqlite file; never touches the original until verification passes.
Run:  python3 scripts/rebuild_quran_script_words.py
"""
import os, sys, json, sqlite3, difflib, unicodedata, collections, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DB   = os.path.join(ROOT, 'QUL_data', 'quran_script.db')
LAYOUT   = os.path.join(ROOT, 'QUL_data', 'mushaf_layout_inferred.db')
QPC_JSON = os.path.join(ROOT, 'QUL_data', 'quran_text', 'QPC Hafs.json')
OUT_DB   = os.path.join(ROOT, 'QUL_data', 'quran_script.rebuilt.db')

WAQF_SYMBOL_CHARS = set('ۖۗۘۙۚۛۜ')
AR_DIGITS = set('٠١٢٣٤٥٦٧٨٩')


def skel(x):
    """Letter skeleton: fold sukun variant, drop tatweel + combining marks."""
    x = ''.join({'ْ': 'ۡ'}.get(c, c) for c in (x or ''))
    x = x.replace('ـ', '')  # tatweel
    return ''.join(c for c in x if not unicodedata.combining(c))


def strip_waqf(tok):
    return ''.join(c for c in (tok or '') if c not in WAQF_SYMBOL_CHARS)


def vk(k):
    s, a = k.split(':'); return (int(s), int(a))


def load_layout_seq():
    """Return sorted list of (word_index, token) from layout ayah/Fatiha-basmala lines."""
    con = sqlite3.connect(LAYOUT); con.row_factory = sqlite3.Row
    seq = {}
    for r in con.execute(
        "SELECT line_type, first_word_id, last_word_id, surah_number, line_text "
        "FROM pages WHERE first_word_id IS NOT NULL ORDER BY first_word_id"
    ):
        if r['line_type'] not in ('ayah', 'basmallah'):
            continue
        if r['line_type'] == 'basmallah' and r['surah_number'] != 1:
            continue
        toks = (r['line_text'] or '').split()
        span = r['last_word_id'] - r['first_word_id'] + 1
        for i, t in enumerate(toks):
            if i < span:
                wi = r['first_word_id'] + i
                seq.setdefault(wi, t)
    con.close()
    return sorted(seq.items())


def load_qpc_seq():
    gt = json.load(open(QPC_JSON, encoding='utf-8'))
    seq = []
    for k in sorted(gt, key=vk):
        s, a = vk(k)
        for p, t in enumerate(gt[k]['text'].split(), 1):
            seq.append([s, a, p, t])
    return seq, gt


def assign_word_index(lay_seq, qpc_seq):
    """Return dict qpc_pos -> word_index, plus a list of unresolved notes."""
    A = [skel(t) for _, t in lay_seq]
    B = [skel(t) for *_, t in qpc_seq]
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    ops = sm.get_opcodes()

    assign = {}          # qpc index -> word_index
    pend_ins = []        # (j1, j2) qpc blocks needing ids
    pend_del = []        # (i1, i2) layout id blocks unused
    notes = []

    for tag, i1, i2, j1, j2 in ops:
        if tag == 'equal':
            for k in range(i2 - i1):
                assign[j1 + k] = lay_seq[i1 + k][0]
        elif tag == 'replace':
            la = i2 - i1; qb = j2 - j1
            if la == qb:
                # positional 1:1 (tatweel/sajda variants) — keep layout word_index
                for k in range(la):
                    assign[j1 + k] = lay_seq[i1 + k][0]
            elif la < qb:
                # One physical glyph spans >1 QPC tokens (ligature مَالِيَ→مَا+لِيَ,
                # or a fused word+number). Map every QPC sub-token to the SAME layout
                # word_index; row-building groups them into one glyph row.
                for k in range(qb):
                    assign[j1 + k] = lay_seq[i1 + min(k, la - 1)][0]
                notes.append(('fused', i1, i2, j1, j2))
            else:
                # >1 layout glyphs map to a single QPC token; give each its own id,
                # last QPC token absorbs the trailing layout ids (rare; surah-88 spot)
                for k in range(la):
                    assign[j1 + min(k, qb - 1)] = lay_seq[i1 + k][0]
                # ensure 1:1 forward for the qpc tokens that exist
                for k in range(qb):
                    assign[j1 + k] = lay_seq[i1 + min(k, la - 1)][0]
                notes.append(('shrink', i1, i2, j1, j2))
        elif tag == 'insert':
            pend_ins.append((j1, j2))
        elif tag == 'delete':
            pend_del.append((i1, i2))

    # Resolve moves: match an inserted QPC block to a deleted layout block with
    # identical skeleton sequence (and equal length).
    used_del = set()
    for (j1, j2) in pend_ins:
        want = [skel(qpc_seq[j][3]) for j in range(j1, j2)]
        matched = None
        for di, (i1, i2) in enumerate(pend_del):
            if di in used_del:
                continue
            if (i2 - i1) == (j2 - j1) and [skel(lay_seq[i][1]) for i in range(i1, i2)] == want:
                matched = (di, i1, i2); break
        if not matched:
            notes.append(('unresolved_insert', j1, j2)); continue
        di, i1, i2 = matched
        used_del.add(di)
        for k in range(j2 - j1):
            assign[j1 + k] = lay_seq[i1 + k][0]
    for di, (i1, i2) in enumerate(pend_del):
        if di not in used_del:
            notes.append(('unresolved_delete', i1, i2))
    return assign, notes


def fix_fused_ids(assign, qpc_seq, lay_used):
    """Give placeholder-fused extra tokens a real free id right after their base."""
    # Collect all currently-used ids
    used = set(assign.values())
    # Find duplicates (placeholders share base id) and reassign extras.
    pos_by_id = collections.defaultdict(list)
    for qp, wi in assign.items():
        pos_by_id[wi].append(qp)
    for wi, positions in pos_by_id.items():
        if len(positions) == 1:
            continue
        positions.sort()
        # keep the first (lowest qpc pos) at wi; move the rest to free ids after wi
        for extra in positions[1:]:
            cand = wi + 1
            while cand in used:
                cand += 1
            assign[extra] = cand
            used.add(cand)
    return assign


def main():
    lay_seq = load_layout_seq()
    qpc_seq, gt = load_qpc_seq()
    print(f"layout seq: {len(lay_seq)}   qpc seq: {len(qpc_seq)}")

    assign, notes = assign_word_index(lay_seq, qpc_seq)

    # every qpc word must have an id
    missing = [j for j in range(len(qpc_seq)) if j not in assign]
    print(f"assigned: {len(assign)}/{len(qpc_seq)}   missing: {len(missing)}")
    if notes:
        print("notes (ligature/fused glyph spots):")
        for n in notes:
            print("   ", n)
    if missing:
        print("ABORT: incomplete assignment")
        for j in missing[:20]:
            print("  missing qpc", qpc_seq[j])
        sys.exit(1)

    # Preserve existing orthography where a correct word already sat at that
    # word_index (honour "preserve sukun style"); else use QPC token.
    old = {}
    ocon = sqlite3.connect(SRC_DB)
    for wi, to in ocon.execute("SELECT word_index, text_original FROM words"):
        old[wi] = to
    ocon.close()

    # Group QPC tokens that share a word_index (a single physical glyph) into one
    # row, in QPC order. One row per word_index = one glyph (original design).
    grouped = collections.OrderedDict()   # word_index -> {'sa':(s,a),'toks':[...]}
    for j, (s, a, p, t) in enumerate(qpc_seq):
        wi = assign[j]
        g = grouped.get(wi)
        if g is None:
            grouped[wi] = {'sa': (s, a), 'toks': [t]}
        else:
            g['toks'].append(t)

    # Renumber position sequentially within each verse, in word_index order.
    rows = []
    pos_counter = collections.Counter()
    for wi in sorted(grouped):
        g = grouped[wi]
        s, a = g['sa']
        pos_counter[(s, a)] += 1
        p = pos_counter[(s, a)]
        joined = ''.join(g['toks'])               # merged glyph text (usually 1 token)
        ot = old.get(wi)
        text_original = ot if (ot is not None and skel(ot) == skel(joined)) else joined
        rows.append((wi, f"{s}:{a}:{p}", s, a, strip_waqf(text_original), text_original))

    # Copy the original DB (keeps schema, indexes, and the build-time `waqf`
    # table) and replace only the `words` rows.
    if os.path.exists(OUT_DB):
        os.remove(OUT_DB)
    shutil.copy(SRC_DB, OUT_DB)
    out = sqlite3.connect(OUT_DB)
    out.execute("DELETE FROM words")
    out.executemany(
        "INSERT INTO words (word_index, word_key, surah, ayah, text, text_original) "
        "VALUES (?,?,?,?,?,?)", rows)
    out.commit()
    out.execute("PRAGMA foreign_keys=ON")
    bad = out.execute("PRAGMA integrity_check").fetchone()[0]
    out.close()
    print(f"wrote {len(rows)} rows -> {OUT_DB}  (integrity: {bad})")


if __name__ == '__main__':
    main()
