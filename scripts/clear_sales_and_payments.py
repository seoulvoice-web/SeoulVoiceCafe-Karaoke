#!/usr/bin/env python3
"""Backup DB and clear all sales: delete tickets and clear payments files.

Usage: run from project root with the virtualenv Python.
"""
from pathlib import Path
import shutil
import sys
from datetime import datetime

# ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app, db
from sqlalchemy import text
import os
import json


def backup_file(src: Path):
    if not src.exists():
        return None
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    dst = src.with_name(src.name + '.bak.' + stamp)
    shutil.copy2(src, dst)
    return dst


def main():
    with app.app_context():
        # Determine DB path if SQLite
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI')
        print('Database URI:', db_uri)
        backed = []
        if db_uri and db_uri.startswith('sqlite:'):
            # sqlite:///relative or sqlite:////absolute
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
            print('Non-sqlite DB or unknown URI; will attempt SQL deletes via engine connection.')

        # Count tickets before
        try:
            engine = getattr(db, 'engine', None) or db.get_engine()
            with engine.connect() as conn:
                try:
                    res_before = conn.execute(text('SELECT COUNT(*) FROM ticket')).scalar()
                except Exception:
                    res_before = None
                print('Tickets before:', res_before)
                # delete tickets
                try:
                    conn.execute(text('DELETE FROM ticket'))
                    print('Deleted all rows from ticket table.')
                except Exception as e:
                    print('Failed deleting tickets via SQL:', e)
                try:
                    res_after = conn.execute(text('SELECT COUNT(*) FROM ticket')).scalar()
                except Exception:
                    res_after = None
                print('Tickets after:', res_after)
        except Exception as e:
            print('DB engine error:', e)

        # Clear payments files in data/
        data_dir = Path(app.root_path) / 'data'
        payments_file = data_dir / 'payments.json'
        notifications_file = data_dir / 'payment_notifications.json'
        for f in (payments_file, notifications_file):
            try:
                if f.exists():
                    bak = backup_file(f)
                    print('Backed up', f, '->', bak)
                f.write_text('[]', encoding='utf-8')
                print('Cleared', f)
            except Exception as e:
                print('Failed clearing', f, e)

        print('Done. Sales and payments cleared. Backups:', backed)


if __name__ == '__main__':
    main()
