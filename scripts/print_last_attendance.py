import sqlite3
import os

base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
db_candidates = [os.path.join(base, 'users.db'), os.path.join(base, 'instance', 'users.db')]
DB = None
for cand in db_candidates:
    if os.path.exists(cand) and os.path.getsize(cand) > 0:
        DB = cand
        break
if not DB:
    DB = db_candidates[0]

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT * FROM attendance ORDER BY id DESC LIMIT 10')
rows = cur.fetchall()
for r in rows:
    print(dict(r))
conn.close()
