import sqlite3
import os
DB1 = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'users.db'))
DB2 = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'users.db'))
print('Checking paths:')
print(' -', DB1)
print(' -', DB2)
DB = None
if os.path.exists(DB1):
    DB = DB1
elif os.path.exists(DB2):
    DB = DB2

if not DB:
    print('DB no existe en ninguna de las rutas')
else:
    print('Usando DB:', DB)
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cur.fetchall()
    print('Tables:', tables)
    for t in tables:
        name = t[0]
        print('\nSchema for', name)
        for row in cur.execute(f"PRAGMA table_info('{name}')"):
            print(row)
    conn.close()
