import sqlite3
conn = sqlite3.connect('QUL_data/waqf_symbols.db')
rows = conn.execute("SELECT DISTINCT symbols FROM waqf_symbols WHERE source='indopak_nastaleeq'").fetchall()

STRUCTURAL = {0x06DF}  # verse-end circle
PUA_MIN = 0xE000       # Private Use Area start

# Collect all distinct "waqf ruling" characters (non-structural, non-PUA)
waqf_chars = set()
pua_chars = set()
structural_chars = set()

for (s,) in rows:
    for c in s:
        cp = ord(c)
        if cp in STRUCTURAL:
            structural_chars.add(cp)
        elif cp >= PUA_MIN:
            pua_chars.add(cp)
        else:
            waqf_chars.add(cp)

print("=== Structural chars (filtered) ===")
for cp in sorted(structural_chars):
    print(f"  U+{cp:04X}  {chr(cp)!r}")

print(f"\n=== PUA chars (filtered) — {len(pua_chars)} distinct values ===")
print(f"  Range: U+{min(pua_chars):04X} to U+{max(pua_chars):04X}")

print("\n=== Actual waqf ruling chars ===")
for cp in sorted(waqf_chars):
    print(f"  U+{cp:04X}  {chr(cp)!r}  char={chr(cp)}")

conn.close()
