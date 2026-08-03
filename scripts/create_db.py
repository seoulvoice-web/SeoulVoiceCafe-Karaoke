import os
import sys

# Asegurar que el directorio raíz del proyecto esté en sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import db, app

with app.app_context():
    db.create_all()
    print('OK: DB creada (users.db)')
