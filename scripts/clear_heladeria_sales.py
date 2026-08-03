#!/usr/bin/env python3
"""Respalda la base de datos y elimina solo los tickets que contienen productos de `heladeria`.

Uso: ejecutar desde la raíz del proyecto con el Python del virtualenv.
"""
from pathlib import Path
import shutil
import sys
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app, db, Ticket, get_heladeria_product_ids, ticket_is_heladeria
from sqlalchemy import text


def backup_file(src: Path):
    if not src.exists():
        return None
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    dst = src.with_name(src.name + '.bak.' + stamp)
    shutil.copy2(src, dst)
    return dst


def main():
    with app.app_context():
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        print('Database URI:', db_uri)
        backed = []
        if db_uri and db_uri.startswith('sqlite:'):
            path = db_uri.split('sqlite:///')[-1]
            db_path = Path(path)
            if not db_path.is_absolute():
                db_path = Path(app.root_path) / db_path
            if db_path.exists():
                bak = backup_file(db_path)
                print('Backed up DB to', bak)
                backed.append(str(bak))
            else:
                print('DB file not found at', db_path)
        else:
            print('Non-sqlite DB or unknown URI; will attempt deletes via engine connection.')

        hel_ids = get_heladeria_product_ids() or set()
        print('Heladeria product IDs:', hel_ids)

        deleted = []
        try:
            q = db.session.query(Ticket).filter(Ticket.snacks == True)
            tickets = q.order_by(Ticket.created_at).all()
            print('Found', len(tickets), 'tickets with snacks=True to examine')
            for t in tickets:
                try:
                    if ticket_is_heladeria(t):
                        deleted.append({'id': t.id, 'created_at': t.created_at.isoformat(), 'created_by': t.created_by, 'snacks_list': t.snacks_list, 'price': t.price})
                        db.session.delete(t)
                except Exception as e:
                    print('Error examining ticket', t.id, e)
            db.session.commit()
            print('Deleted', len(deleted), 'heladeria tickets')
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            print('DB error during deletion:', e)

        # guardar respaldo de tickets eliminados
        if deleted:
            data_dir = Path(app.root_path) / 'data'
            stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
            out_file = data_dir / f'deleted_heladeria_tickets.{stamp}.json'
            try:
                out_file.write_text(json.dumps(deleted, indent=2, ensure_ascii=False), encoding='utf-8')
                print('Wrote backup of deleted tickets to', out_file)
            except Exception as e:
                print('Failed writing backup file:', e)

        print('Done. Backups:', backed)


if __name__ == '__main__':
    main()
