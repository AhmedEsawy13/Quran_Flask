import sqlite3

conn = sqlite3.connect('QUL_data/mushaf_layout_inferred.db')
res = conn.execute("SELECT * FROM shamarly_glyphs WHERE arabic_word LIKE 'ۚ' OR arabic_word LIKE 'ۖ' LIMIT 5").fetchall()
print(res)
