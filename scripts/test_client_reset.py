import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, serializer

with app.test_client() as c:
    token = serializer.dumps('test', salt='password-reset-salt')
    path = f'/reset/{token}'
    resp = c.get(path)
    print('In-process GET', path, '->', resp.status_code)
    print('Body preview:\n', resp.get_data(as_text=True)[:400])
