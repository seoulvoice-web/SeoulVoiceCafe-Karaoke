#!/usr/bin/env python3
import os, sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, Attendance
from datetime import datetime, date, timezone

with app.app_context():
    # Ensure 'status' column exists in SQLite table
    try:
        engine = getattr(db, 'engine', None) or db.get_engine()
        with engine.connect() as conn:
            res = conn.execute("PRAGMA table_info('attendance')").fetchall()
            cols = [r[1] for r in res]
            if 'status' not in cols:
                try:
                    conn.execute("ALTER TABLE attendance ADD COLUMN status VARCHAR(30)")
                    print('Added column status to attendance table')
                except Exception:
                    pass
    except Exception:
        pass
    today = date.today()
    # sample: check_in 08:05, check_out 17:00 (UTC-aware)
    check_in = datetime(today.year, today.month, today.day, 8, 5, 0, tzinfo=timezone.utc)
    check_out = datetime(today.year, today.month, today.day, 17, 0, 0, tzinfo=timezone.utc)
    # Use raw INSERT to avoid issues if the DB schema hasn't been migrated
    from sqlalchemy import text
    params = {
        'user_id': 1,
        'username': 'demo',
        'role': 'Staff',
        'date': today.isoformat(),
        'check_in': check_in.isoformat(sep=' '),
        'check_out': check_out.isoformat(sep=' '),
        'duration_minutes': int((check_out - check_in).total_seconds()//60),
        'note': 'Registro de prueba generado automáticamente',
        'created_by': 'script',
        'created_at': datetime.now(timezone.utc).isoformat(sep=' '),
    }
    try:
        engine = getattr(db, 'engine', None) or db.get_engine()
        with engine.begin() as conn:
            # Insert without `status` column to avoid schema mismatch
            r = conn.execute(text('''
                INSERT INTO attendance (user_id, username, role, date, check_in, check_out, duration_minutes, note, created_by, created_at)
                VALUES (:user_id, :username, :role, :date, :check_in, :check_out, :duration_minutes, :note, :created_by, :created_at)
            '''), params)
            try:
                lastid = r.lastrowid
            except Exception:
                lastid = None
        print('Inserted attendance, lastrowid=', lastid)
    except Exception as e:
        print('Insert failed:', e)
