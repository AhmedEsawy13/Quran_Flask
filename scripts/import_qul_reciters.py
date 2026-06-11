#!/usr/bin/env python3
"""Import extra memorization reciters from the Quranic Universal Audio (QUL) release.

Source (CC-BY-4.0):
  https://github.com/Wider-Community/quranic-universal-audio/releases/tag/v1.1.0

Each reciter is published as a .zip containing word_timestamps.json.gz (and
verse/letter variants) + catalog.json. The memorize player only needs
`word_timestamps.json.gz` (same format already used for Husary).

Usage:
  1) Download the reciter .zip(s) you want from the release above.
  2) Run:  python scripts/import_qul_reciters.py <reciter_id> <path-to.zip>
     e.g.  python scripts/import_qul_reciters.py minshawi ~/Downloads/minshawi.zip
     This extracts word_timestamps.json.gz into reciters/<dir>/ where <dir> is
     the path configured in app.py MEMORIZATION_RECITERS[<reciter_id>]['dir'].
  3) Make sure MEMORIZATION_RECITERS[<reciter_id>] in app.py has the right
     'audio_tmpl' (a per-surah mp3 URL, e.g. https://server10.mp3quran.net/minsh/{surah:03d}.mp3).
  4) Restart the app — the reciter now appears in the memorize «القارئ» list.

This script does NOT download anything itself (the release assets are large and
network access varies); point it at a zip you've already downloaded.
"""
import os
import sys
import zipfile

# reciter_id -> target dir (must match app.py MEMORIZATION_RECITERS[*]['dir'])
TARGET_DIRS = {
    'husary':      'reciters/mahmoud_khalil_al_husary_mp3quran',
    'ahmed_amer':  'reciters/ahmed_amer_tvquran',
    'burhaji':     'reciters/mohammed_burhaji_yt',
    'minshawi':    'reciters/mohammed_siddiq_al_minshawi_mp3quran',
    'abdulbasit':  'reciters/abdulbasit_abdulsamad_tarteel',
    'afasy':       'reciters/afasy_qul',
    'banna':       'reciters/mahmoud_ali_al_banna_qdc',
    'maher':       'reciters/maher_al_muaiqly_qdc',
    'sufi':        'reciters/abdur_rashid_sufi_qdc',
    'maasaraawi':  'reciters/ahmed_issa_al_maasaraawi_mp3quran',
    'abdulhakam':  'reciters/mahmoud_abdul_hakam_mp3quran',
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WANTED = ('word_timestamps.json.gz', 'verse_timestamps.json.gz', 'catalog.json')


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        print("known reciter_ids:", ', '.join(TARGET_DIRS))
        sys.exit(1)
    rid, zip_path = sys.argv[1], sys.argv[2]
    if rid not in TARGET_DIRS:
        sys.exit(f"unknown reciter_id {rid!r}; add it to TARGET_DIRS + app.py MEMORIZATION_RECITERS")
    if not os.path.exists(zip_path):
        sys.exit(f"zip not found: {zip_path}")
    out_dir = os.path.join(ROOT, TARGET_DIRS[rid])
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base in WANTED:
                with z.open(member) as src, open(os.path.join(out_dir, base), 'wb') as dst:
                    dst.write(src.read())
                print("wrote", os.path.join(TARGET_DIRS[rid], base))
    if not os.path.exists(os.path.join(out_dir, 'word_timestamps.json.gz')):
        sys.exit("ERROR: word_timestamps.json.gz not found in the zip")
    print(f"done — set MEMORIZATION_RECITERS['{rid}']['audio_tmpl'] in app.py and restart.")


if __name__ == '__main__':
    main()
