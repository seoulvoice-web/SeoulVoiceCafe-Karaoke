#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import sqlite3

BASE = Path(__file__).resolve().parent.parent
db_path = BASE / 'instance' / 'users.db'
if not db_path.exists():
    print('instance DB not found at', db_path)
    raise SystemExit(1)

now = datetime.now(timezone.utc)
today_start = datetime(now.year, now.month, now.day)
ts_str = today_start.strftime('%Y-%m-%d 00:00:00')

bak = db_path.with_name(db_path.name + '.bak.' + datetime.utcnow().strftime('%Y%m%d%H%M%S'))
import shutil
shutil.copy2(db_path, bak)
print('Backed up instance DB to', bak)

conn = sqlite3.connect(str(db_path))
cur = conn.cursor()
try:
    cur.execute("SELECT COUNT(*) FROM ticket WHERE datetime(created_at) >= datetime(?)", (ts_str,))
    before = cur.fetchone()[0]
    print('Tickets to delete (created today or later):', before)
    cur.execute("DELETE FROM ticket WHERE datetime(created_at) >= datetime(?)", (ts_str,))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM ticket",)
    after = cur.fetchone()[0]
    print('Tickets after delete:', after)
finally:
    conn.close()
