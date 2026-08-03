import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app

import werkzeug
if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = '3.1.5'

with app.test_client() as c:
    resp = c.post('/login', data={'username':'test','password':'test123'}, follow_redirects=True)
    print('Status code:', resp.status_code)
    body = resp.get_data(as_text=True)
    if 'Entrar' in body or 'Iniciar sesión' in body or '/login' in resp.request.path:
        print('Login failed')
    else:
        print('Login OK')
    print('\nResponse preview:\n', body[:500])
