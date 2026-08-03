import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import db, app
from sqlalchemy import text

with app.app_context():
    try:
        r = db.session.execute(text("SELECT COUNT(*) as c FROM attendance")).fetchone()
        print(r[0] if r else 0)
    except Exception as e:
        print('error', e)
