import os
import sqlite3
from werkzeug.security import generate_password_hash

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'users.db'))
print('DB:', DB)
if not os.path.exists(DB):
    print('DB no encontrada, abortando')
    raise SystemExit(1)

conn = sqlite3.connect(DB)
cur = conn.cursor()
username = 'test'
password = 'test123'
cur.execute('SELECT id FROM user WHERE username=?', (username,))
if cur.fetchone():
    print(f"Usuario '{username}' ya existe")
else:
    ph = generate_password_hash(password)
    cur.execute('INSERT INTO user (username, password_hash) VALUES (?, ?)', (username, ph))
    conn.commit()
    print(f"OK: usuario '{username}' creado con contraseña '{password}'")
conn.close()
