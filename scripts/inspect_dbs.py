#!/usr/bin/env python3
from pathlib import Path
import sqlite3
import json
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
DBS = [BASE / 'users.db', BASE / 'instance' / 'users.db']

def inspect_db(p):
    print('\nDB file:', p)
    if not p.exists():
        print('  (not found)')
        return
    conn = sqlite3.connect(str(p))
    cur = conn.cursor()
    try:
        cur.execute("SELECT count(*) FROM ticket")
        c = cur.fetchone()[0]
        print('  tickets count:', c)
        cur.execute("SELECT id, buyer_name, price, room_number, created_at FROM ticket ORDER BY created_at DESC LIMIT 10")
        rows = cur.fetchall()
        for r in rows:
            print('   ', r)
    except Exception as e:
        print('  error querying ticket:', e)
    conn.close()

if __name__ == '__main__':
    for db in DBS:
        inspect_db(db)
