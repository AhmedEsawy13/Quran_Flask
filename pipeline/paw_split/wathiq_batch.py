"""Split Wathiq pages, repairing line breaks where the print differs from the old Madinah layout.

    python3 pipeline/paw_split/wathiq_batch.py 15 56 190 ...
A page whose split leaves a word without ink (or a letter body no word claims) is re-split with the
boundary word moved to the neighbouring line; the variant with fewest such flags wins (ties: no move).

A line break one word off does not always leave a flag: the text's extra (or missing) word is squeezed
in and every word after it slides one place (p400: the print ends line 5 with «وَقَالُوا۟», the layout
opens line 6 with it, so «تَحْزَنْ»'s sign landed on «إِنَّا»). Such a line aligns badly, so lines whose
alignment cost is high are tried with a word moved across each of their edges; a move is kept when it
lowers the page's total cost clearly and adds no flag.
"""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'artifacts' / os.environ.get('PAW_WORK', 'wathiq-trace')
COST_SUSPECT = float(os.environ.get('COST_SUSPECT', '3.5'))   # a line's alignment cost above this is tried
COST_GAIN = float(os.environ.get('COST_GAIN', '1.5'))         # a move must lower the page's cost by this much


LAST = {}


def run(page, moves):
    LAST[page] = list(moves)
    env = dict(os.environ, MOVES=','.join(moves))
    subprocess.run([sys.executable, str(Path(__file__).with_name('wathiq_split.py')), str(page)],
                   env=env, check=True, capture_output=True)
    c = json.load(open(WORK / f'paw-words-{page:03d}.json'))['checks']
    lines = set(c['empty_lines']) | {u['layout_line'] for u in c['unclaimed_bodies']}
    flags = len(c['words_without_ink']) + len(c['unclaimed_bodies']) + len(c['forced_lines'])
    costs = {int(k): v for k, v in c.get('line_costs', {}).items()}
    return flags, lines, costs


def edge_moves(ln, moves, repeat=False):
    """Moves of one word across either edge of layout line ln (a move may repeat: two words off)."""
    out = []
    for m in (f'{ln}>', f'{ln - 1}>', f'{ln}<', f'{ln + 1}<'):
        if 1 <= int(m[:-1]) <= 15 and (repeat or m not in moves):
            out.append(m)
    return out


def split_page(page):
    moves = []
    score, lines, costs = run(page, moves)
    while score:
        tries = []
        for ln in sorted(lines):
            for m in edge_moves(ln, moves):
                try:
                    tries.append((run(page, moves + [m]), m))
                except subprocess.CalledProcessError:
                    pass
        if not tries:
            break
        (best, best_lines, best_costs), m = min(tries, key=lambda t: t[0][0])
        if best >= score:
            break
        moves.append(m); score, lines, costs = best, best_lines, best_costs
    # line breaks that leave no flag: follow the alignment cost
    tried = set()
    for _ in range(4):
        suspects = [ln for ln, v in sorted(costs.items()) if v > COST_SUSPECT and ln not in tried]
        if not suspects:
            break
        tried.update(suspects)
        tries = []
        for ln in suspects:
            for m in edge_moves(ln, moves, repeat=True):
                opposite = m[:-1] + ('<' if m[-1] == '>' else '>')
                if opposite in moves:
                    continue
                try:
                    tries.append((run(page, moves + [m]), m))
                except subprocess.CalledProcessError:
                    pass
        ok = [t for t in tries if t[0][0] <= score]
        if not ok:
            continue
        (f, l, c), m = min(ok, key=lambda t: sum(t[0][2].values()))
        if sum(c.values()) <= sum(costs.values()) - COST_GAIN:
            moves.append(m); score, lines, costs = f, l, c
            tried -= {int(m[:-1]), int(m[:-1]) + (1 if m[-1] == '>' else -1)}   # look at the lines it changed again
    if LAST.get(page) != moves:
        run(page, moves)        # leave the chosen variant on disk
    print(page, 'moves', moves or '-', 'flags', score, 'cost', round(sum(costs.values()), 2), flush=True)


if __name__ == '__main__':
    for page in map(int, sys.argv[1:]):
        split_page(page)
