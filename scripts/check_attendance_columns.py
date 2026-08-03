import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from sqlalchemy import text
from app import db

with app.app_context():
    engine = getattr(db, 'engine', None) or db.get_engine(app)
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info('attendance')")).fetchall()
        for r in rows:
            print(r)
