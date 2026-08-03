#!/usr/bin/env python3
import requests, re, sys, datetime

BASE = 'http://127.0.0.1:3000'

s = requests.Session()
try:
    r = s.get(BASE + '/asistencia', timeout=5)
except Exception as e:
    print('ERROR: no se pudo conectar a', BASE, '->', e)
    sys.exit(2)
if r.status_code != 200:
    print('ERROR: GET /asistencia returned', r.status_code)
    sys.exit(2)

html = r.text
m_csrf = re.search(r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']', html)
csrf = m_csrf.group(1) if m_csrf else None
m_id = re.search(r'<tr[^>]+data-id=["\'](\d+)["\']', html)
if not m_id:
    print('No se encontró ningún registro en la tabla (no hay <tr data-id=...>).')
    sys.exit(0)
att_id = m_id.group(1)
print('Found attendance id =', att_id, 'csrf=', bool(csrf))

# build payload: set check_in to today 08:05:00 to demonstrate 'Retraso' if policy defines >08:00
today = datetime.date.today()
check_in_dt = datetime.datetime(today.year, today.month, today.day, 8, 5, 0)
# use ISO with Z
check_in_iso = check_in_dt.isoformat() + 'Z'
# set check_out to 17:00
check_out_dt = datetime.datetime(today.year, today.month, today.day, 17, 0, 0)
check_out_iso = check_out_dt.isoformat() + 'Z'

payload = {
    'check_in': check_in_iso,
    'check_out': check_out_iso,
    'note': 'Prueba automática: Asistencia / Retraso ejemplos'
}
headers = {'Content-Type': 'application/json', 'X-Requested-With':'XMLHttpRequest'}
if csrf:
    headers['X-CSRF-Token'] = csrf

post_url = f"{BASE}/asistencia/{att_id}/edit"
print('POST', post_url)
try:
    r2 = s.post(post_url, json=payload, headers=headers, timeout=8)
except Exception as e:
    print('ERROR POST failed ->', e)
    sys.exit(3)
print('Status', r2.status_code)
print('Response:', r2.text)

try:
    j = r2.json()
    print('Parsed JSON:', j)
except Exception:
    pass

# fetch page again and show first row attrs
r3 = s.get(BASE + '/asistencia')
if r3.status_code == 200:
    m_row = re.search(r'<tr[^>]+data-id=["\']%s["\'][^>]*>([\s\S]*?)</tr>'%att_id, r3.text)
    if m_row:
        print('\nRow HTML after edit:')
        print(m_row.group(0))

print('\nDone')
