const express = require('express');
const path = require('path');
const bodyParser = require('body-parser');
const session = require('express-session');

const app = express();
const PORT = process.env.PORT || 3000;

// Config
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));
app.use(bodyParser.urlencoded({ extended: false }));
app.use(express.static(path.join(__dirname, 'public')));
app.use(session({
  secret: 'seoul-voice-secret',
  resave: false,
  saveUninitialized: false,
}));

// Simple hardcoded user for demo
const DEMO_USER = { username: 'admin', password: 'admin123' };

function requireAuth(req, res, next) {
  if (req.session && req.session.user) return next();
  return res.redirect('/login');
}

function adminRequired(req, res, next) {
  if (req.session && req.session.user && req.session.user.is_admin) return next();
  return res.redirect('/');
}

// Routes
app.get('/login', (req, res) => {
  if (req.session && req.session.user) return res.redirect('/');
  res.render('login', { error: null });
});

app.post('/login', (req, res) => {
  const { username, password } = req.body;
  if (username === DEMO_USER.username && password === DEMO_USER.password) {
    req.session.user = { username };
    return res.redirect('/');
  }
  return res.render('login', { error: 'Usuario o contraseña incorrectos' });
});

app.get('/logout', (req, res) => {
  req.session.destroy(() => res.redirect('/login'));
});

app.get('/', requireAuth, (req, res) => {
  res.render('dashboard', { user: req.session.user });
});

app.get('/cine', requireAuth, (req, res) => {
  const videos = [
    { title: 'Big Buck Bunny (MP4)', src: 'https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_1MB.mp4', type: 'mp4' },
    { title: 'YouTube Example', src: 'https://www.youtube.com/embed/YE7VzlLtp-4', type: 'youtube' }
  ];
  res.render('cine', { user: req.session.user, videos });
});

app.get('/karaoke', requireAuth, (req, res) => {
  const lyrics = [
    'Esta es la primera línea del karaoke',
    'Aquí va la segunda línea por si acaso',
    'La tercera línea suena ahora',
    'Y finalmente la última línea'
  ];
  res.render('karaoke', { user: req.session.user, lyrics });
});

// Gestión / Inventario - placeholders
app.get('/admin', requireAuth, adminRequired, (req, res) => {
  res.render('simple_page', { user: req.session.user, heading: 'Panel de administración', message: null, items: [] });
});

app.get('/staff/new', requireAuth, adminRequired, (req, res) => {
  res.render('simple_page', { user: req.session.user, heading: 'Agregar personal', show_form: true });
});

app.post('/staff/new', requireAuth, adminRequired, (req, res) => {
  // placeholder: en producción guardar en BD
  const name = req.body.name || 'Sin nombre';
  res.render('simple_page', { user: req.session.user, heading: 'Agregar personal', message: `Personal "${name}" agregado (demo).` });
});

app.get('/productos', requireAuth, (req, res) => {
  const items = ['Micrófono A', 'Cable XLR', 'Auriculares Pro'];
  res.render('simple_page', { user: req.session.user, heading: 'Productos', items });
});

app.get('/contactos', requireAuth, (req, res) => {
  const items = ['Contacto 1: 63050841', 'Contacto 2: 72554129', 'Correo: ejemplo@correo.com'];
  res.render('simple_page', { user: req.session.user, heading: 'Contactos', items });
});

app.get('/ubicacion', requireAuth, (req, res) => {
  res.render('simple_page', { user: req.session.user, heading: 'Ubicación', message: 'Dirección: Av. Cochabamba- al frente de la inglesia jesus obrero - galeria - Piso 1' });
});

app.get('/galeria', requireAuth, (req, res) => {
  const images = ['/img/logo.svg'];
  res.render('simple_page', { user: req.session.user, heading: 'Galería', items: images });
});

app.get('/reservas', requireAuth, (req, res) => {
  const items = ['Reserva 1: Sala A - 2026-02-01 10:00', 'Reserva 2: Sala B - 2026-02-02 15:00'];
  res.render('simple_page', { user: req.session.user, heading: 'Reservas / Citas', items });
});

app.get('/salas', requireAuth, (req, res) => {
  const items = ['Sala A', 'Sala B', 'Sala VIP'];
  res.render('simple_page', { user: req.session.user, heading: 'Salas', items });
});

app.get('/precios', requireAuth, (req, res) => {
  const items = ['Sala A: 20 USD/h', 'Sala VIP: 50 USD/h'];
  res.render('simple_page', { user: req.session.user, heading: 'Precios', items });
});

app.get('/eventos', requireAuth, (req, res) => {
  const items = ['Evento 1: Concierto demo - 2026-03-10', 'Evento 2: Karaoke Night - 2026-03-20'];
  res.render('simple_page', { user: req.session.user, heading: 'Eventos', items });
});

app.get('/asistencia', requireAuth, adminRequired, (req, res) => {
  const items = ['Admin: 95% presente', 'Staff A: 88% presente'];
  res.render('simple_page', { user: req.session.user, heading: 'Asistencia (admin/personal)', items });
});

app.listen(PORT, () => console.log(`Server running on http://localhost:${PORT}`));
