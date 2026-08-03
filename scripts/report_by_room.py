import sqlite3
import os
import json
import argparse
from datetime import datetime


def find_db():
    DB1 = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'users.db'))
    DB2 = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'users.db'))
    if os.path.exists(DB1):
        return DB1
    if os.path.exists(DB2):
        return DB2
    return None


def query_by_room(db_path, start_date=None, end_date=None):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    q = "SELECT room_number, COUNT(*) as tickets, COALESCE(SUM(price),0.0) as revenue FROM ticket"
    params = []
    clauses = []
    if start_date:
        clauses.append("created_at >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("created_at <= ?")
        params.append(end_date)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " GROUP BY room_number ORDER BY room_number"
    cur.execute(q, params)
    rows = cur.fetchall()
    result = []
    total_tickets = 0
    total_revenue = 0.0
    for r in rows:
        room, tickets, revenue = r
        result.append({'room': room, 'tickets': tickets, 'revenue_bob': revenue})
        total_tickets += tickets
        total_revenue += revenue
    conn.close()
    return result, total_tickets, total_revenue


def parse_allowed_rooms():
    # Leer lista de salas permitidas desde la variable de entorno ROOMS (ej: '1,2')
    v = os.environ.get('ROOMS')
    if not v:
        return None
    try:
        parts = [p.strip() for p in v.split(',') if p.strip()]
        nums = set()
        for p in parts:
            nums.add(int(p))
        return nums
    except Exception:
        return None


def write_csv(path, per_room):
    import csv
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        writer = csv.writer(fh)
        writer.writerow(['room', 'tickets', 'revenue_bob'])
        for r in per_room:
            writer.writerow([r['room'], r['tickets'], r['revenue_bob']])


def main():
    parser = argparse.ArgumentParser(description='Report by room')
    parser.add_argument('--start', help='Start date (inclusive) YYYY-MM-DD or ISO')
    parser.add_argument('--end', help='End date (inclusive) YYYY-MM-DD or ISO')
    parser.add_argument('--csv', help='Output CSV path')
    parser.add_argument('--json', help='Output JSON path')
    args = parser.parse_args()

    db = find_db()
    if not db:
        raise SystemExit('DB no encontrada')

    start = None
    end = None
    # Accept date-only strings and convert to ISO datetimes
    try:
        if args.start:
            start = args.start if 'T' in args.start else args.start + 'T00:00:00'
        if args.end:
            end = args.end if 'T' in args.end else args.end + 'T23:59:59'
    except Exception:
        pass

    per_room, total_tickets, total_revenue = query_by_room(db, start, end)

    # Filtrar solo salas permitidas si ROOMS está definida (ej: ROOMS=1,2)
    allowed = parse_allowed_rooms()
    if allowed is not None:
        per_room = [r for r in per_room if (r.get('room') in allowed)]
        total_tickets = sum(r['tickets'] for r in per_room)
        total_revenue = sum(r['revenue_bob'] for r in per_room)

    output = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'db_path': db,
        'per_room': per_room,
        'total_tickets': total_tickets,
        'total_revenue_bob': total_revenue,
    }

    if args.json:
        os.makedirs(os.path.dirname(args.json), exist_ok=True)
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(output, fh, indent=2, ensure_ascii=False)

    if args.csv:
        write_csv(args.csv, per_room)

    if not args.csv and not args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
