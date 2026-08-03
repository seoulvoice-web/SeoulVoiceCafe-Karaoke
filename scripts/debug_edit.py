import os, sys, traceback
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db, Attendance

with app.app_context():
    client = app.test_client()
    # prepare admin session and csrf
    token = 'debug-token-123'
    with client.session_transaction() as sess:
        sess['user'] = {'username': os.environ.get('ADMIN_USERNAME','admin'), 'is_admin': True, 'role': 'Admin'}
        sess['csrf_token'] = token
    # pick an attendance id
    a = Attendance.query.order_by(Attendance.id.desc()).first()
    if not a:
        print('No attendance records found')
        sys.exit(1)
    att_id = a.id
    print('Using attendance id', att_id)
    payload = {'check_in': a.check_in.isoformat() if a.check_in else '', 'check_out': a.check_out.isoformat() if a.check_out else ''}
    # try edit with same values to see response
    try:
        r = client.post(f'/asistencia/{att_id}/edit', json=payload, headers={'X-Requested-With':'XMLHttpRequest','X-CSRF-Token': token})
        print('Status', r.status_code)
        try:
            print('JSON:', r.get_json())
        except Exception:
            print('Text:', r.get_data(as_text=True))
    except Exception as e:
        print('Exception during request')
        traceback.print_exc()
