import sqlite3
conn = sqlite3.connect('QUL_data/waqf_symbols.db')
rows = conn.execute("SELECT DISTINCT symbols FROM waqf_symbols WHERE source='indopak_nastaleeq' ORDER BY symbols").fetchall()
seen = set()
unique = []
for (s,) in rows:
    key = tuple(ord(c) for c in s)
    if key not in seen:
        seen.add(key)
        unique.append(s)
for sym in sorted(unique, key=lambda s: [ord(c) for c in s]):
    codepoints = ' '.join(hex(ord(c)) for c in sym)
    print(f"{repr(sym):40s} codepoints: {codepoints}")
conn.close()
