import os
import shutil
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

"""
Escanea la base de datos de usuarios (instance/users.db) y re-hashea
las entradas de la columna `password_hash` que parecen ser contraseñas
en texto plano (no en formato de hash de Werkzeug).

Uso:
  python scripts/hash_plain_passwords.py

Hará una copia de seguridad automática del fichero DB antes de modificarlo.
"""


BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_PATHS = [
    os.path.join(BASE, 'instance', 'users.db'),
    os.path.join(BASE, 'users.db'),
]


def find_db():
    for p in DB_PATHS:
        if os.path.exists(p):
            return p
    return None


def looks_hashed(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    s = s.strip()
    # Werkzeug hashes typicaly start with 'pbkdf2:' or 'argon2'
    if s.startswith('pbkdf2:') or s.startswith('argon2:'):
        return True
    # fallback: if it contains many hashed-looking segments (':', '$') assume hashed
    if ':' in s and '$' in s:
        return True
    return False


def backup_db(path):
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak = f"{path}.bak.{ts}"
    shutil.copy2(path, bak)
    return bak


def main():
    db = find_db()
    if not db:
        print('No se encontró la base de datos en:', DB_PATHS)
        return 1
    print('Usando DB:', db)
    bak = backup_db(db)
    print('Backup creado en', bak)

    conn = sqlite3.connect(db)
    cur = conn.cursor()
    try:
        cur.execute('SELECT id, username, password_hash FROM user')
    except Exception as e:
        print('Error leyendo tabla user:', e)
        conn.close()
        return 1

    rows = cur.fetchall()
    updated = 0
    for r in rows:
        uid, uname, ph = r
        if not ph:
            print(f'Usuario {uname} (id={uid}): sin contraseña, omitiendo')
            continue
        if looks_hashed(ph):
            # ya está hasheada
            continue
        # asumimos que `ph` contiene la contraseña en texto plano — la re-hasheamos
        newh = generate_password_hash(ph)
        try:
            cur.execute('UPDATE user SET password_hash=? WHERE id=?', (newh, uid))
            updated += 1
            print(f'Usuario {uname} (id={uid}): re-hasheada')
        except Exception as e:
            print(f'Error actualizando usuario {uname}:', e)

    conn.commit()
    conn.close()
    print(f'Completado. Actualizadas {updated} filas. Backup: {bak}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
