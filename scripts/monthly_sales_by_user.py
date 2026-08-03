#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import app, db, Ticket, User, read_settings
from sqlalchemy import func

def main(year=None, month=None):
    with app.app_context():
        now = datetime.now(timezone.utc)
        year = year or now.year
        month = month or now.month
        start = datetime(int(year), int(month), 1, tzinfo=timezone.utc)
        if int(month) == 12:
            end = datetime(int(year)+1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(int(year), int(month)+1, 1, tzinfo=timezone.utc)

        # left join users to get role
        q = db.session.query(
            Ticket.created_by.label('username'),
            func.count(Ticket.id).label('tickets'),
            func.coalesce(User.role, 'Unknown').label('role')
        ).outerjoin(User, User.username == Ticket.created_by)
        q = q.filter(Ticket.created_at >= start, Ticket.created_at < end)
        q = q.group_by(Ticket.created_by, User.role).order_by(func.count(Ticket.id).desc())

        rows = q.all()
        print(f'Month: {year}-{int(month):02d} (from {start.isoformat()} to {end.isoformat()})')
        print('Usuario\tRol\tTickets')
        total = 0
        for r in rows:
            user = r[0] or 'UNKNOWN'
            role = r[2] or 'Unknown'
            cnt = int(r[1])
            total += cnt
            print(f'{user}\t{role}\t{cnt}')
        print('Total\t-\t{}'.format(total))

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--year', type=int)
    p.add_argument('--month', type=int)
    args = p.parse_args()
    main(args.year, args.month)
