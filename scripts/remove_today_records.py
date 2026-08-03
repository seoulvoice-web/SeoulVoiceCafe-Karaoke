#!/usr/bin/env python3
"""Remove all ticket rows and payments created from start of today (UTC).

Creates backups before modifying DB/files.
"""
from pathlib import Path
import sys
from datetime import datetime, timezone
import json
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import app, db
from sqlalchemy import text


def backup_file(p: Path):
    if not p.exists():
        return None
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    dst = p.with_name(p.name + '.bak.' + stamp)
    shutil.copy2(p, dst)
    return dst


def main():
    with app.app_context():
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day)
        ts_str = today_start.strftime('%Y-%m-%d 00:00:00')
        print('Removing records with created_at >=', ts_str)

        # Delete tickets from DB where created_at >= today_start
        try:
            engine = getattr(db, 'engine', None) or db.get_engine()
            with engine.connect() as conn:
                # backup DB file if sqlite
                db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
                if db_uri.startswith('sqlite'):
                    # path extraction
                    path = db_uri.split('sqlite:///')[-1]
                    db_path = Path(path)
                    if not db_path.is_absolute():
                        db_path = Path(app.root_path) / db_path
                    if db_path.exists():
                        bak = backup_file(db_path)
                        print('DB backup:', bak)
                # perform delete using textual comparison
                res = conn.execute(text("DELETE FROM ticket WHERE datetime(created_at) >= datetime(:ts)"), {'ts': ts_str})
                print('Deleted tickets (rowcount may be unknown):', getattr(res, 'rowcount', 'unknown'))
        except Exception as e:
            print('DB delete error:', e)

        # Clear payments entries from today in data/payments.json
        data_dir = Path(app.root_path) / 'data'
        payments_file = data_dir / 'payments.json'
        notifications_file = data_dir / 'payment_notifications.json'
        for f in (payments_file, notifications_file):
            try:
                if not f.exists():
                    continue
                bak = backup_file(f)
                print('Backed up', f, '->', bak)
                with f.open('r', encoding='utf-8') as fh:
                    arr = json.load(fh)
                kept = []
                for e in arr:
                    ca = e.get('created_at')
                    if not ca:
                        # keep if no date
                        kept.append(e)
                        continue
                    # parse ISO with optional 'Z'
                    s = ca
                    if s.endswith('Z'):
                        s = s[:-1]
                    try:
                        dt = datetime.fromisoformat(s)
                    except Exception:
                        # try common format
                        try:
                            dt = datetime.strptime(s, '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            kept.append(e)
                            continue
                    if dt >= datetime(now.year, now.month, now.day, tzinfo=dt.tzinfo):
                        # skip (delete)
                        continue
                    kept.append(e)
                with f.open('w', encoding='utf-8') as fh:
                    json.dump(kept, fh, indent=2, ensure_ascii=False)
                print('Filtered', f, '-> kept', len(kept), 'entries')
            except Exception as e:
                print('Failed processing', f, e)

        print('Done.')


if __name__ == '__main__':
    main()
