#!/usr/bin/env python3
"""Inserta un ticket de prueba (sala karaoke) y muestra métricas desde hoy.

Usar el entorno virtual del proyecto para ejecutar este script.
"""
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so `from app import ...` works when running from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app, db, Ticket, read_settings
from sqlalchemy import func


def main():
    with app.app_context():
        # Ensure snacks_total column exists in SQLite (simple migration)
        try:
            engine = db.get_engine()
            url = str(engine.url)
            if url.startswith('sqlite'):
                res = engine.execute("PRAGMA table_info('ticket')").fetchall()
                cols = [r[1] for r in res]
                if 'snacks_total' not in cols:
                    try:
                        engine.execute("ALTER TABLE ticket ADD COLUMN snacks_total FLOAT DEFAULT 0.0")
                        print('Added snacks_total column to ticket table')
                    except Exception as e:
                        print('Could not add snacks_total column:', e)
        except Exception:
            pass
        # crear ticket de prueba usando SQL directo (evita errores si la columna snacks_total no existe aún)
        buyer_name = 'TEST_USR'
        buyer_id = 'TEST_ID'
        room_number = 1
        price = 50.0
        snacks_total = 5.0
        created_at = datetime.now(timezone.utc)
        entry_time = created_at
        snacks_list_json = json.dumps([{'id': 0, 'qty': 1, 'price': snacks_total}])
        engine = db.get_engine()
        from sqlalchemy import text
        with engine.connect() as conn:
            # Insert only into known columns (omit snacks_total if DB doesn't have it)
            try:
                res = conn.execute(
                    text(
                        "INSERT INTO ticket (buyer_name, buyer_id, price, room_number, created_at, exit_time, entry_time, promo, snacks, promo_type, snacks_list) VALUES (:bn, :bid, :price, :room, :created_at, :exit_time, :entry_time, :promo, :snacks, :promo_type, :snacks_list)"
                    ),
                    {
                        'bn': buyer_name,
                        'bid': buyer_id,
                        'price': price + snacks_total,
                        'room': room_number,
                        'created_at': created_at,
                        'exit_time': None,
                        'entry_time': entry_time,
                        'promo': 0,
                        'snacks': 1,
                        'promo_type': None,
                        'snacks_list': snacks_list_json,
                    }
                )
                print('Inserted ticket via SQL (rowcount):', getattr(res, 'rowcount', 'unknown'))
            except Exception as e:
                print('Failed to insert via simple INSERT:', e)

        # calcular métricas desde hoy UTC para salas permitidas
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        cfg = read_settings() or {}
        allowed_env = cfg.get('ROOMS') or os.environ.get('ROOMS')
        if allowed_env is None:
            allowed = {1, 2}
        else:
            try:
                allowed = set(int(x.strip()) for x in allowed_env.split(',') if x.strip())
            except Exception:
                allowed = {1, 2}

        monthly_sum = db.session.query(func.coalesce(func.sum(Ticket.price), 0.0)).filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).scalar() or 0.0
        tickets_count = db.session.query(func.count(Ticket.id)).filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).scalar() or 0
        room_q = db.session.query(Ticket.room_number.label('room'), func.count(Ticket.id).label('tickets'), func.coalesce(func.sum(Ticket.price), 0.0).label('income'))
        room_q = room_q.filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).group_by('room').order_by('room').all()

        print('Metrics since', today_start.isoformat())
        print('Monthly income (sum):', float(monthly_sum))
        print('Tickets count:', int(tickets_count))
        # snacks_sum not computed here (Ticket.price already incluye snacks)
        print('Room breakdown:')
        for r in room_q:
            print(' - room', int(r[0]), 'tickets', int(r[1]), 'income', float(r[2] or 0.0))


if __name__ == '__main__':
    main()
