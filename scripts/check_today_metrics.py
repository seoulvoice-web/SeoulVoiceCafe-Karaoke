#!/usr/bin/env python3
"""Muestra métricas desde el inicio del día (UTC): tickets y suma de precios."""
import sys
from pathlib import Path
from datetime import datetime, timezone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app, db, Ticket, read_settings
from sqlalchemy import func
import os


def main():
    with app.app_context():
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

        tickets_count = db.session.query(func.count(Ticket.id)).filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).scalar() or 0
        monthly_sum = db.session.query(func.coalesce(func.sum(Ticket.price), 0.0)).filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).scalar() or 0.0

        print('Desde:', today_start.isoformat())
        print('Tickets vendidos (salas permitidas):', int(tickets_count))
        print('Ingreso acumulado (Bs):', float(monthly_sum))


if __name__ == '__main__':
    main()
