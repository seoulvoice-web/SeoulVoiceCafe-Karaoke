import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, serializer
from flask import url_for

with app.app_context():
    print('Rutas activas:')
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint)):
        print(f' - {rule.rule}  -> endpoint: {rule.endpoint}')

    token = serializer.dumps('test', salt='password-reset-salt')
    path = url_for('reset_password', token=token, _external=False)
    print('\nToken generado para `test`:', token)
    print('URL local (PC):', f'http://localhost:3000{path}')
    print('URL en red (misma Wi-Fi):', f'http://192.168.0.241:3000{path}')
