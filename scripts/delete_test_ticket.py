#!/usr/bin/env python3
"""Borra tickets de prueba con buyer_name 'TEST_USR' y buyer_id 'TEST_ID'."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app, db, Ticket


def main():
    with app.app_context():
        # Use raw SQL DELETE to avoid ORM column mismatch if DB schema is older
        try:
            engine = db.get_engine()
        except Exception:
            engine = getattr(db, 'engine', None)
        from sqlalchemy import text
        with engine.connect() as conn:
            try:
                res = conn.execute(text("DELETE FROM ticket WHERE buyer_name = :bn AND buyer_id = :bid"), {'bn': 'TEST_USR', 'bid': 'TEST_ID'})
                # rowcount may be available
                cnt = getattr(res, 'rowcount', None)
                if cnt is None:
                    print('Delete executed; rowcount unknown.')
                else:
                    print('Deleted', cnt, 'test tickets.')
            except Exception as e:
                print('Failed to delete test tickets via SQL:', e)


if __name__ == '__main__':
    main()
