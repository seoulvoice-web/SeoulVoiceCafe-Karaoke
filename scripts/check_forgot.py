import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

with app.test_client() as c:
    resp = c.get('/forgot')
    print('GET /forgot ->', resp.status_code)
    print(resp.get_data(as_text=True)[:500])
