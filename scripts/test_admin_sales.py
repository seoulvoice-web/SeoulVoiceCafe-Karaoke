#!/usr/bin/env python3
import sys
import os
import traceback

# Asegurar que el directorio raíz del proyecto esté en sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app

def main(year=None, month=None, fmt='csv'):
    try:
        qs = ''
        if year and month:
            qs = f'?year={year}&month={month}&format={fmt}'
        else:
            qs = f'?format={fmt}'
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess['user'] = {'username': 'admin', 'is_admin': True, 'role': 'Admin'}
            resp = client.get('/admin/sales_by_user' + qs)
            print('STATUS:', resp.status_code)
            if fmt == 'pdf':
                out = f"out_sales_by_user_{year or 'current'}_{month or 'curr'}.pdf"
                with open(out, 'wb') as f:
                    f.write(resp.get_data())
                print('PDF escrito en', out)
            else:
                print(resp.get_data(as_text=True))
                if resp.status_code != 200:
                    print('RESPUESTA (texto):')
                    print(resp.get_data(as_text=True))
    except Exception:
        traceback.print_exc()

if __name__ == '__main__':
    # Opcional: pasar año y mes por args
    import sys
    if len(sys.argv) >= 4:
        main(sys.argv[1], sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3:
        main(sys.argv[1], sys.argv[2])
    else:
        main()
