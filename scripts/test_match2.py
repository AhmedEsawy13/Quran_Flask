import sqlite3

MUSHAF_WAQF_DATABASE = 'QUL_data/mushaf_waqf.db'

conn = sqlite3.connect(MUSHAF_WAQF_DATABASE)
rows = conn.execute("SELECT الكلمة, المدينة, ورش FROM waqf WHERE السورة=58 AND الآية=11").fetchall()
for r in rows:
    print(r)
