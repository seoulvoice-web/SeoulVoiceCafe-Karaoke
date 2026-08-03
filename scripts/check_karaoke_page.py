from app import app

with app.test_client() as c:
    resp = c.post('/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    print('LOGIN_STATUS:', resp.status_code)
    r = c.get('/karaoke')
    html = r.data.decode('utf-8')
    found = ('Compra de boletos' in html) or ('ticketForm' in html)
    print('FOUND_TICKET_SECTION:', found)
    if found:
        idx = html.find('Compra de boletos') if 'Compra de boletos' in html else html.find('ticketForm')
        start = max(0, idx - 200)
        end = min(len(html), idx + 600)
        print(html[start:end])
    else:
        print(html[:1000])
