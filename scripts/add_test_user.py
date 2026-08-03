import os
import sys

# Asegurar que el directorio raíz del proyecto esté en sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db, User

with app.app_context():
    username = 'test'
    password = 'test123'
    existing = User.query.filter_by(username=username).first()
    if existing:
        print(f"Usuario '{username}' ya existe.")
    else:
        user = User.create(username, password)
        db.session.add(user)
        db.session.commit()
        print(f"OK: usuario '{username}' creado con contraseña '{password}'.")
