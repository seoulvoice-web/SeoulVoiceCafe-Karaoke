import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app

print('SQLALCHEMY_DATABASE_URI =', app.config.get('SQLALCHEMY_DATABASE_URI'))
print('Absolute DB path guess:')
uri = app.config.get('SQLALCHEMY_DATABASE_URI') or ''
if uri.startswith('sqlite:///'):
    path = uri.replace('sqlite:///', '')
    import os
    print(os.path.abspath(path))
else:
    print(uri)
