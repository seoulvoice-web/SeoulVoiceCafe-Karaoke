import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, serializer
from flask import url_for

# Configurar SERVER_NAME temporalmente para construir URLs externas
app.config['SERVER_NAME'] = 'localhost:3000'

with app.app_context():
    token = serializer.dumps('test', salt='password-reset-salt')
    path = url_for('reset_password', token=token, _external=True)
    print('Token:', token)
    print('URL (localhost):', path)
    # Reemplazar hostname para la IP local en la misma red
    print('URL (red local):', path.replace('localhost', '192.168.0.241'))
