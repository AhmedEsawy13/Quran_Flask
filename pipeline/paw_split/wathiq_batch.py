"""Split Wathiq pages, repairing line breaks where the print differs from the old Madinah layout.

    python3 pipeline/paw_split/wathiq_batch.py 15 56 190 ...
A page whose split leaves a word without ink (or a letter body no word claims) is re-split with the
boundary word moved to the neighbouring line; the variant with fewest such flags wins (ties: no move).
"""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'artifacts' / 'wathiq-trace'


def run(page, moves):
    env = dict(os.environ, MOVES=','.join(moves))
    subprocess.run([sys.executable, str(Path(__file__).with_name('wathiq_split.py')), str(page)],
                   env=env, check=True, capture_output=True)
    c = json.load(open(WORK / f'paw-words-{page:03d}.json'))['checks']
    lines = set(c['empty_lines']) | {u['layout_line'] for u in c['unclaimed_bodies']}
    return len(c['words_without_ink']) + len(c['unclaimed_bodies']) + len(c['forced_lines']), lines


for page in map(int, sys.argv[1:]):
    moves = []
    score, lines = run(page, moves)
    while score:
        tries = []
        for ln in sorted(lines):
            for m in (f'{ln}>', f'{ln - 1}>', f'{ln}<', f'{ln + 1}<'):
                if 1 <= int(m[:-1]) <= 15 and m not in moves:
                    try:
                        tries.append((run(page, moves + [m]), m))
                    except subprocess.CalledProcessError:
                        pass
        if not tries:
            break
        (best, best_lines), m = min(tries, key=lambda t: t[0][0])
        if best >= score:
            break
        moves.append(m); score, lines = best, best_lines
    run(page, moves)            # leave the chosen variant on disk
    print(page, 'moves', moves or '-', 'flags', score)
