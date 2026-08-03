import os
import sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, User

with app.app_context():
    u = User.query.filter_by(username='test').first()
    if u:
        print("FOUND: test user exists")
    else:
        print("NOT FOUND: test user does not exist")
