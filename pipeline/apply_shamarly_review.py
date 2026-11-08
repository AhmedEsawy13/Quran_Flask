"""Apply the reviewed Shamarly sign cards to the «الشمرلي» waqf column (data/mushaf_waqf.db).

The cards are data/shamarly-waqf/<set>/ (pipeline/paw_split/shamarly_waqf_cards.py); each decision is the sign
printed on the word ('' = none), saved by /mushaf-editor/shamarly-waqf under «الشمرلي · فحص». Only the (أ) cards
change the column: their word is the column's own word. A (ب) card is a candidate near *some* word, so its
verdict stays a note for a person to apply by hand.

The change goes through pipeline/sync_published_waqf.py's machinery: a plan (digest + SQLite SHA-256) that is
checked again at apply time, an ignored backup, one transaction, and a read-back of every changed word. The
baked research caches are not regenerated here (python3 pipeline/precompute_research.py).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pipeline import sync_published_waqf as sp

EDITION = 'الشمرلي'
SIGNS = frozenset({'ص', 'ق', 'ج', 'م', 'لا', 'س', 'ع'})
WORD_PROVIDER = sp._canonical_words      # a test swaps in a small word list


def _token(key: str) -> tuple[int, int, int]:
    """(surah, ayah, zero-based word position) of a script word key 's:a:w'."""
    s, a, w = (int(x) for x in key.split(':'))
    return s, a, w - 1


def build_plan(data: dict, decisions: dict[str, dict], database: Path) -> dict:
    """The column changes the (أ) decisions of one card set ask for, as a digest-checked plan.

    ``decisions`` is {card id: decision row} (modules/mesaha_waqf_review.set_decisions).
    """
    database = Path(database)
    local = sp.load_local_state(database, (EDITION,), word_provider=WORD_PROVIDER)
    marks = local['marks'][EDITION]
    errors = [f'column does not align with the words: {e}' for e in local['errors'][:5]]
    changes, summary = [], {'decided_a': 0, 'unchanged': 0, 'undecided_a': 0, 'b_verdicts': 0}
    for card in data.get('cards', []):
        row = decisions.get(card['id'])
        if card.get('group') != 'A':
            summary['b_verdicts'] += 1 if row else 0
            continue
        if row is None:
            summary['undecided_a'] += 1
            continue
        summary['decided_a'] += 1
        new = (row.get('correct_mark') or '').strip()
        if new and new not in SIGNS:
            errors.append(f'{card["key"]}: unknown sign {new!r}')
            continue
        surah, ayah, token = _token(card['key'])
        current = (marks.get((surah, ayah, token)) or {}).get('symbol', '')
        if new == current:
            summary['unchanged'] += 1
            continue
        changes.append({
            'action': 'update' if current else 'add', 'edition': EDITION, 'surah': surah, 'ayah': ayah,
            'token_index': token, 'word_text': card.get('text') or '', 'old_symbol': current, 'new_symbol': new,
            'updated_at': row.get('updated_at'), 'page': card.get('page'), 'card': card['id'],
        })
    changes.sort(key=lambda c: (c['surah'], c['ayah'], c['token_index']))
    summary['changes'] = len(changes)
    # what a reviewer approves: the same column file and the same changes (the plan's own digest also covers
    # its timestamp, so a rebuilt plan never matches an earlier one)
    stable = json.dumps([sp.database_sha256(database), [(c['surah'], c['ayah'], c['token_index'], c['new_symbol'])
                                                         for c in changes]], ensure_ascii=False)
    plan = {
        'content_digest': hashlib.sha256(stable.encode('utf-8')).hexdigest(),
        'schema_version': sp.SCHEMA_VERSION, 'generated_at': sp._iso_now(), 'source': 'shamarly-waqf review cards',
        'database': str(database.resolve()), 'database_sha256_before': sp.database_sha256(database),
        'editions': [EDITION], 'valid': not errors, 'summary': {EDITION: summary},
        'validation': {'errors': errors, 'warnings': local['warnings'][:5]}, 'changes': changes,
    }
    return sp.finalize_plan(plan)


def apply(plan: dict, database: Path) -> dict:
    """Apply a plan built by :func:`build_plan` (it is verified against the database again first)."""
    return sp.apply_plan(plan, database=Path(database), word_provider=WORD_PROVIDER)
