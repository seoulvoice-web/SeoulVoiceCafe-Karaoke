import os
import sqlite3
import csv
from datetime import datetime

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DB_CANDIDATES = [os.path.join(BASE, 'instance', 'users.db'), os.path.join(BASE, 'users.db')]

def find_db():
    for p in DB_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def rows_to_csv(rows, headers, outpath):
    os.makedirs(os.path.dirname(outpath), exist_ok=True)
    with open(outpath, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        for r in rows:
            w.writerow(r)


def main():
    db = find_db()
    if not db:
        print('No se encontró la base de datos. Buscando en:', DB_CANDIDATES)
        return 1
    print('Usando DB:', db)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Total users
    cur.execute('SELECT COUNT(*) AS total_users FROM "user"')
    total_users = cur.fetchone()['total_users']

    # Admin users
    try:
        cur.execute('SELECT COUNT(*) AS admins FROM "user" WHERE is_admin=1')
        admins = cur.fetchone()['admins']
    except Exception:
        admins = None

    # Total tickets and revenue
    try:
        cur.execute('SELECT COUNT(*) AS total_tickets, ROUND(SUM(price),2) AS total_revenue FROM ticket')
        t = cur.fetchone()
        total_tickets = t['total_tickets']
        total_revenue = t['total_revenue']
    except Exception:
        total_tickets = 0
        total_revenue = 0.0

    # Reservations last 30 days
    try:
        cur.execute("SELECT COUNT(*) AS last_30d, ROUND(SUM(price),2) AS revenue_30d FROM ticket WHERE created_at >= datetime('now','-30 days')")
        r30 = cur.fetchone()
        last_30d = r30['last_30d']
        revenue_30d = r30['revenue_30d']
    except Exception:
        last_30d = 0
        revenue_30d = 0.0

    # Reservations per month (last 12 months)
    try:
        cur.execute("SELECT strftime('%Y-%m', created_at) AS month, COUNT(*) AS reservations, ROUND(SUM(price),2) AS total_bob FROM ticket GROUP BY month ORDER BY month DESC LIMIT 12")
        monthly = cur.fetchall()
        monthly_rows = [(r['month'], r['reservations'], r['total_bob']) for r in monthly]
        rows_to_csv(monthly_rows, ['month','reservations','total_bob'], os.path.join(BASE,'scripts','reports','monthly_revenue.csv'))
    except Exception:
        monthly_rows = []

    # Top users by reservations (join by buyer_id if matches username)
    try:
        cur.execute("SELECT t.buyer_id, COUNT(*) AS cnt, ROUND(SUM(t.price),2) AS total_spent FROM ticket t GROUP BY t.buyer_id ORDER BY cnt DESC LIMIT 10")
        top_buyers = cur.fetchall()
        top_rows = [(r['buyer_id'], r['cnt'], r['total_spent']) for r in top_buyers]
        rows_to_csv(top_rows, ['buyer_id','reservations','total_spent'], os.path.join(BASE,'scripts','reports','top_buyers.csv'))
    except Exception:
        top_rows = []

    # Users with reservation counts (attempt join if buyer_id equals username)
    try:
        cur.execute("SELECT u.id, u.username, u.email, COUNT(t.id) AS reservations FROM \"user\" u LEFT JOIN ticket t ON t.buyer_id = u.username GROUP BY u.id ORDER BY reservations DESC")
        users_with_counts = cur.fetchall()
        user_rows = [(r['id'], r['username'], r['email'], r['reservations']) for r in users_with_counts]
        rows_to_csv(user_rows, ['id','username','email','reservations'], os.path.join(BASE,'scripts','reports','users_reservations.csv'))
    except Exception:
        user_rows = []

    report = {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'db_path': db,
        'total_users': total_users,
        'admin_users': admins,
        'total_tickets': total_tickets,
        'total_revenue_bob': float(total_revenue) if total_revenue is not None else 0.0,
        'reservations_last_30d': last_30d,
        'revenue_last_30d_bob': float(revenue_30d) if revenue_30d is not None else 0.0,
        'monthly': monthly_rows,
        'top_buyers': top_rows,
        'users_with_reservations_sample': user_rows[:20]
    }

    import json
    out_json = os.path.join(BASE,'scripts','reports','summary.json')
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    print('Informe generado:')
    print(' - total_users:', total_users)
    print(' - admin_users:', admins)
    print(' - total_tickets:', total_tickets)
    print(' - total_revenue_bob:', total_revenue)
    print(' - reservations_last_30d:', last_30d)
    print(' - revenue_last_30d_bob:', revenue_30d)
    print('\nCSV generados en scripts/reports/')
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
