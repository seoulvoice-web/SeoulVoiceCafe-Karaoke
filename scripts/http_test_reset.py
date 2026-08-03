import os
import sys
import urllib.request
import urllib.error
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import serializer, app

with app.app_context():
    token = serializer.dumps('test', salt='password-reset-salt')
    path = f'/reset/{token}'
    urls = [
        f'http://127.0.0.1:3000{path}',
        f'http://localhost:3000{path}',
        f'http://192.168.0.241:3000{path}',
    ]
    for u in urls:
        try:
            print('\nRequesting', u)
            req = urllib.request.Request(u, method='GET')
            with urllib.request.urlopen(req, timeout=5) as r:
                code = r.getcode()
                body = r.read(1000).decode('utf-8', errors='replace')
                print('Status:', code)
                print('Body preview:\n', body)
        except urllib.error.HTTPError as he:
            print('HTTPError:', he.code, he.reason)
            try:
                print('Body:\n', he.read().decode('utf-8', errors='replace')[:1000])
            except Exception:
                pass
        except Exception as e:
            print('Error requesting URL:', e)
