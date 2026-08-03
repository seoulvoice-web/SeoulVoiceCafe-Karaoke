#!/usr/bin/env python3
import os, shutil, glob, sqlite3, json
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
now = datetime.now().strftime('%Y%m%d%H%M%S')

# DB files to consider
db_candidates = [os.path.join(ROOT, 'users.db'), os.path.join(ROOT, 'instance', 'users.db')]
# JSON files
payments_json = os.path.join(ROOT, 'data', 'payments.json')
reservations_json = os.path.join(ROOT, 'data', 'reservations.json')

backs = []

def backup_file(p):
    if not os.path.exists(p):
        return None
    dst = p + f'.bak.{now}'
    shutil.copy2(p, dst)
    return dst

print('Iniciando reset seleccionado. Se crearán backups antes de borrar datos.')
for dbf in db_candidates:
    if os.path.exists(dbf):
        b = backup_file(dbf)
        print(f'Backup DB: {dbf} -> {b}')
        backs.append(b)
        try:
            conn = sqlite3.connect(dbf)
            cur = conn.cursor()
            # borrar tickets y attendance si existen
            for tbl in ('ticket', 'attendance'):
                try:
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl,))
                    if cur.fetchone():
                        cur.execute(f"DELETE FROM {tbl}")
                        print(f'Borradas filas en {tbl} de {dbf}')
                except Exception as e:
                    print(f'No se pudo borrar tabla {tbl} en {dbf}: {e}')
            conn.commit()
            try:
                cur.execute('VACUUM')
            except Exception:
                pass
            conn.close()
        except Exception as e:
            print(f'Error manejando DB {dbf}: {e}')
    else:
        print(f'No existe DB: {dbf}')

# JSON backups and clear
for jf in (payments_json, reservations_json):
    if os.path.exists(jf):
        b = backup_file(jf)
        print(f'Backup JSON: {jf} -> {b}')
        backs.append(b)
        try:
            with open(jf, 'w', encoding='utf-8') as fh:
                json.dump([], fh, ensure_ascii=False, indent=2)
            print(f'Contenido de {jf} reemplazado por lista vacía')
        except Exception as e:
            print(f'Error escribiendo {jf}: {e}')
    else:
        print(f'No existe JSON: {jf}')

print('\nOperación completada. Backups creados:')
for p in backs:
    print(' -', p)
print('\nRevisa los backups antes de reiniciar la aplicación.')
