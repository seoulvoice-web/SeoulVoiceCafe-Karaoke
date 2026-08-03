import sys
import os
# ensure project root is on sys.path so `import app` works when running from scripts/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import perform_attendance_migration, app

if __name__ == '__main__':
    with app.app_context():
        res = perform_attendance_migration()
        print(res)
