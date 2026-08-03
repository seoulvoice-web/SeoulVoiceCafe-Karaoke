import pkgutil
import importlib
import os
import contextlib

# Polyfill para compatibilidad con Python 3.14: Flask (v2.2.x) usa pkgutil.get_loader,
# que fue removido en versiones recientes; si falta, lo recreamos usando importlib.
if not hasattr(pkgutil, 'get_loader'):
    def _pkgutil_get_loader(name):
        # avoid calling find_spec on __main__ (raises ValueError when __spec__ is None)
        try:
            if name == '__main__':
                return None
            spec = importlib.util.find_spec(name)
            return spec.loader if spec else None
        except Exception:
            return None
    pkgutil.get_loader = _pkgutil_get_loader

from flask import Flask, render_template, request, redirect, session, url_for, flash, make_response, jsonify, Response, abort
from sqlalchemy.exc import OperationalError
from sqlalchemy import text, inspect, case
from sqlalchemy import func
from types import SimpleNamespace
from functools import wraps
from uuid import uuid4
import urllib.parse
import re
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask_socketio import SocketIO, join_room, leave_room
import json
from datetime import datetime, timedelta, date, timezone
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import shutil
import platform
import os as _os
import io
import csv
import subprocess

# Evitar llamadas WMI problemáticas en Windows al importar librerías (p.ej. SQLAlchemy)
# Algunas instalaciones de Python en Windows (p.ej. Python 3.14) intentan consultar WMI
# desde platform.machine() lo que puede colgar o lanzar OSError en algunos sistemas.
# Forzamos un valor seguro para `platform.machine` en Windows para evitar ese bloqueo.
try:
    if platform.system().lower().startswith('win'):
        _forced = _os.environ.get('PLATFORM_MACHINE', 'AMD64')
        platform.machine = lambda: _forced
except Exception:
    pass
import smtplib
import ssl
from email.message import EmailMessage
import traceback
import secrets
import string
from functools import wraps as _wraps

app = Flask(__name__)
# SECRET_KEY: preferir variable de entorno. Valor por defecto solo para desarrollo local.
DEFAULT_SECRET_KEY = 'seoul-voice-secret-py'
app.secret_key = os.environ.get('SECRET_KEY', DEFAULT_SECRET_KEY)

# Configuración de URL base para generación de enlaces externos (ej: enlaces de recuperación)
# Se puede sobreescribir con la variable de entorno SERVER_NAME
app.config.setdefault('SERVER_NAME', os.environ.get('SERVER_NAME', '192.168.0.241:3000'))
app.config.setdefault('PREFERRED_URL_SCHEME', os.environ.get('PREFERRED_URL_SCHEME', 'http'))
# Habilitar recarga automática de plantillas para ver cambios sin reiniciar
app.config.setdefault('TEMPLATES_AUTO_RELOAD', True)
app.jinja_env.auto_reload = True

# Socket.IO real-time notifications
socketio = SocketIO(cors_allowed_origins='*', async_mode='eventlet')
socketio.init_app(app)


def normalize_room(room):
    """Normaliza y valida el identificador de sala.
    Acepta entradas como 1, '1', 'Sala 1', 'room-1' y extrae el número.
    Devuelve el número de sala (int) si está permitido por la variable de entorno
    `ROOMS` (p.ej. '1,2,3') o el conjunto por defecto {1,2}. Retorna None si inválido.
    """
    try:
        if room is None:
            return None
        s = str(room).strip().lower()
        m = re.search(r"(\d+)", s)
        if not m:
            return None
        num = int(m.group(1))
        # Leer lista permitida desde variable de entorno 'ROOMS' (coma-separada)
        allowed_env = os.environ.get('ROOMS')
        if allowed_env:
            try:
                allowed = set(int(x.strip()) for x in str(allowed_env).split(',') if x.strip())
            except Exception:
                allowed = {1, 2}
        else:
            allowed = {1, 2}
        return num if num in allowed else None
    except Exception:
        return None


# Socket.IO events: allow admin clients to join an 'admins' room
@socketio.on('join_admins')
def handle_join_admins(data=None):
    try:
        user = session.get('user') or {}
        if user.get('is_admin'):
            join_room('admins')
                # No emitir notificación automática al unirse para evitar toasts en UI
            try:
                    app.logger.debug('Admin joined admins room (notification suppressed)')
            except Exception:
                    pass
    except Exception:
        app.logger.exception('join_admins handler failed')

@socketio.on('leave_admins')
def handle_leave_admins(data=None):
    try:
        leave_room('admins')
    except Exception:
        app.logger.exception('leave_admins handler failed')


# Allow clients to join/leave room-specific channels (e.g. karaoke rooms)
@socketio.on('join_room')
def handle_join_room(data=None):
    try:
        if not data:
            return
        room_raw = data.get('room') or data.get('room_number')
        norm = normalize_room(room_raw)
        if not norm:
            return
        join_room(f'room_{norm}')
        socketio.emit('notification', {'message': f'Joined room {norm}', 'type': 'system'}, room=f'room_{norm}')
    except Exception:
        app.logger.exception('join_room handler failed')


@socketio.on('leave_room')
def handle_leave_room(data=None):
    try:
        if not data:
            return
        room_raw = data.get('room') or data.get('room_number')
        norm = normalize_room(room_raw)
        if not norm:
            return
        leave_room(f'room_{norm}')
    except Exception:
        app.logger.exception('leave_room handler failed')

# Precio por defecto del boleto (en Bolivianos). Se puede sobreescribir
# con la variable de entorno DEFAULT_TICKET_PRICE
app.config.setdefault('DEFAULT_TICKET_PRICE', float(os.environ.get('DEFAULT_TICKET_PRICE', '35.0')))
app.config.setdefault('TAX_RATE', float(os.environ.get('TAX_RATE', '0.0')))

# Demo user
DEMO_USER = {'username': 'admin', 'password': 'admin123'}

# Configuración de base de datos (SQLite por defecto)
app.config.setdefault('SQLALCHEMY_DATABASE_URI', os.environ.get('DATABASE_URL', 'sqlite:///users.db'))
app.config.setdefault('SQLALCHEMY_TRACK_MODIFICATIONS', False)
db = SQLAlchemy(app)

def ensure_user_is_admin_column():
    # Asegura que la columna is_admin exista en la tabla user (SQLite).
    try:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        with engine.connect() as conn:
            # comprobar columnas
            res = conn.execute(text("PRAGMA table_info('user')")).fetchall()
            cols = [r[1] for r in res]
            # añadir columnas si faltan
            if 'is_admin' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"))
            if 'email' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN email VARCHAR(200)"))
            if 'role' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN role VARCHAR(50) DEFAULT 'Staff'"))
            if 'must_change_password' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN must_change_password BOOLEAN DEFAULT 0"))
            if 'created_by' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN created_by VARCHAR(150)"))
            if 'created_at' not in cols:
                conn.execute(text("ALTER TABLE user ADD COLUMN created_at DATETIME"))
    except Exception:
        # si falla, no rompemos el arranque; la app seguirá funcionando pero sin persistir rol
        pass


def ensure_ticket_snacks_total_column():
    """Asegura que la columna `snacks_total` exista en la tabla `ticket` (SQLite)."""
    try:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        with engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info('ticket')")).fetchall()
                cols = [r[1] for r in res]
            except Exception:
                res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='ticket'"))
                if not res.fetchone():
                    return False
                res = conn.execute(text("PRAGMA table_info('ticket')")).fetchall()
                cols = [r[1] for r in res]
            if 'snacks_total' not in cols:
                try:
                    conn.execute(text("ALTER TABLE ticket ADD COLUMN snacks_total FLOAT DEFAULT 0.0"))
                    app.logger.info('Added snacks_total column to ticket table')
                    return True
                except Exception:
                    app.logger.exception('Failed adding snacks_total column')
                    return False
    except Exception:
        app.logger.exception('ensure_ticket_snacks_total_column failed')
        return False
    return True


def ensure_ticket_created_by_column():
    """Asegura que la columna `created_by` exista en la tabla `ticket` (SQLite)."""
    try:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        with engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info('ticket')")).fetchall()
                cols = [r[1] for r in res]
            except Exception:
                res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='ticket'"))
                if not res.fetchone():
                    return False
                res = conn.execute(text("PRAGMA table_info('ticket')")).fetchall()
                cols = [r[1] for r in res]
            if 'created_by' not in cols:
                try:
                    conn.execute(text("ALTER TABLE ticket ADD COLUMN created_by VARCHAR(150)"))
                    app.logger.info('Added created_by column to ticket table')
                    return True
                except Exception:
                    app.logger.exception('Failed adding created_by column')
                    return False
    except Exception:
        app.logger.exception('ensure_ticket_created_by_column failed')
        return False
    return True


def ensure_ticket_buyer_phone_column():
    """Asegura que la columna `buyer_phone` exista en la tabla `ticket` (SQLite)."""
    try:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        with engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info('ticket')")).fetchall()
                cols = [r[1] for r in res]
            except Exception:
                res = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='ticket'"))
                if not res.fetchone():
                    return False
                res = conn.execute(text("PRAGMA table_info('ticket')")).fetchall()
                cols = [r[1] for r in res]
            if 'buyer_phone' not in cols:
                try:
                    conn.execute(text("ALTER TABLE ticket ADD COLUMN buyer_phone VARCHAR(50)"))
                    app.logger.info('Added buyer_phone column to ticket table')
                    return True
                except Exception:
                    app.logger.exception('Failed adding buyer_phone column')
                    return False
    except Exception:
        app.logger.exception('ensure_ticket_buyer_phone_column failed')
        return False
    return True

# No forzamos la columna aquí; la aseguramos después de crear tablas al arrancar.

# Serializer para tokens de recuperación
serializer = URLSafeTimedSerializer(app.secret_key)


def generate_csrf_token():
    try:
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return session['csrf_token']
    except Exception:
        return ''


@app.context_processor
def inject_csrf_token():
    return {'csrf_token': generate_csrf_token}


@app.context_processor
def inject_notification_count():
    try:
        notes = load_notifications()
        unread = 0
        for n in notes:
            st = (n.get('status') or '').lower()
            if st != 'read':
                unread += 1
        # count public (general) notifications separately (those with 'for_all'=True)
        public_unread = 0
        for n in notes:
            if n.get('for_all') and (n.get('status') or '').lower() != 'read':
                public_unread += 1
        return {'notifications_unread_count': unread, 'public_notifications_unread_count': public_unread}
    except Exception:
        return {'notifications_unread_count': 0, 'public_notifications_unread_count': 0}


def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Only enforce for state-changing requests
        if request.method in ('POST', 'PUT', 'DELETE'):
            token = None
            # Prefer header
            try:
                token = request.headers.get('X-CSRF-Token') or request.form.get('csrf_token')
            except Exception:
                token = None
            if not token or token != session.get('csrf_token'):
                # AJAX requests should get JSON error
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({'status': 'error', 'message': 'CSRF token inválido o faltante'}), 400
                flash('Token CSRF inválido. Vuelve a intentarlo.')
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# Manejador global para mostrar trazas de excepción en respuestas (solo para depuración local)
# No interceptar HTTPException (404, 400, etc.) — permitir que Flask las maneje correctamente.
@app.errorhandler(Exception)
def handle_uncaught_exception(e):
    # Si es una HTTPException (p.ej. 404), re-envíala para que Flask devuelva el código correcto
    if isinstance(e, HTTPException):
        return e
    # Registrar la excepción
    app.logger.exception('Unhandled exception: %s', e)
    tb = traceback.format_exc()
    # Devolver stack trace en texto plano para facilitar depuración local
    return (f"<h3>Error interno del servidor</h3><pre>{tb}</pre>", 500, {'Content-Type': 'text/html; charset=utf-8'})

# Ubicación del fichero de configuración simple (instance/settings.json)
SETTINGS_FILE = lambda: os.path.join(app.root_path, 'instance', 'settings.json')

def read_settings():
    try:
        p = SETTINGS_FILE()
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as fh:
                return json.load(fh) or {}
    except Exception:
        pass
    return {}


def send_email(to_address: str, subject: str, body: str) -> bool:
    """Enviar correo usando configuración almacenada en instance/settings.json.
    Si no hay SMTP configurado, devuelve False.
    """
    cfg = read_settings() or {}
    host = cfg.get('smtp_host') or os.environ.get('SMTP_HOST')
    port = int(cfg.get('smtp_port') or os.environ.get('SMTP_PORT') or 0)
    user = cfg.get('smtp_user') or os.environ.get('SMTP_USER')
    password = cfg.get('smtp_pass') or os.environ.get('SMTP_PASS')
    from_addr = cfg.get('smtp_from') or os.environ.get('SMTP_FROM') or f"no-reply@{os.environ.get('SERVER_NAME','localhost')}"

    if not host or not port:
        # no SMTP configured
        app.logger.info('SMTP no configurado; correo no enviado a %s', to_address)
        return False

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = from_addr
    msg['To'] = to_address
    msg.set_content(body)

    try:
        if port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as server:
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo()
                if server.has_extn('STARTTLS'):
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if user and password:
                    server.login(user, password)
                server.send_message(msg)
        app.logger.info('Correo enviado a %s', to_address)
        return True
    except Exception as e:
        app.logger.exception('Error enviando correo: %s', e)
        return False

def write_settings(d: dict):
    try:
        p = SETTINGS_FILE()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def load_products():
    pfile = os.path.join(app.root_path, 'data', 'products.json')
    if os.path.exists(pfile):
        try:
            with open(pfile, 'r', encoding='utf-8') as fh:
                return json.load(fh) or []
        except Exception:
            return []
    return []


def save_products(products):
    pfile = os.path.join(app.root_path, 'data', 'products.json')
    os.makedirs(os.path.dirname(pfile), exist_ok=True)
    tmp = pfile + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(products, fh, ensure_ascii=False, indent=2)
    try:
        os.replace(tmp, pfile)
    except Exception:
        try:
            os.remove(pfile)
        except Exception:
            pass
        os.replace(tmp, pfile)

def detect_wkhtmltopdf():
    # 1) Check admin-configured path
    cfg = read_settings()
    cfg_path = cfg.get('wkhtmltopdf_path') if isinstance(cfg, dict) else None
    if cfg_path and os.path.exists(cfg_path):
        return cfg_path

    # 2) Respect environment variable
    env_path = os.environ.get('WKHTMLTOPDF_PATH')
    if env_path and os.path.exists(env_path):
        return env_path

    # 3) Common Windows installation locations
    if platform.system().lower().startswith('win'):
        candidates = [
            r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
            r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
        ]
    else:
        candidates = ['/usr/local/bin/wkhtmltopdf', '/usr/bin/wkhtmltopdf']

    for p in candidates:
        if os.path.exists(p):
            return p

    # 4) Try PATH
    which_path = shutil.which('wkhtmltopdf')
    if which_path:
        return which_path

    return None


# Invoice numbering helpers: mantener contadores y mapeo ticket->invoice en JSON ligero
INVOICE_COUNTERS_FILE = lambda: os.path.join(app.root_path, 'data', 'invoice_counters.json')
INVOICE_MAP_FILE = lambda: os.path.join(app.root_path, 'data', 'invoice_map.json')

def load_invoice_counters():
    p = INVOICE_COUNTERS_FILE()
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                return json.load(fh) or {}
        except Exception:
            return {}
    return {}

def save_invoice_counters(d):
    p = INVOICE_COUNTERS_FILE()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, p)
        except Exception:
            try:
                os.remove(p)
            except Exception:
                pass
            os.replace(tmp, p)
        return True
    except Exception:
        return False

def load_invoice_map():
    p = INVOICE_MAP_FILE()
    if os.path.exists(p):
        try:
            with open(p, 'r', encoding='utf-8') as fh:
                return json.load(fh) or {}
        except Exception:
            return {}
    return {}

def save_invoice_map(m):
    p = INVOICE_MAP_FILE()
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(m, fh, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, p)
        except Exception:
            try:
                os.remove(p)
            except Exception:
                pass
            os.replace(tmp, p)
        return True
    except Exception:
        return False

def _get_next_invoice_for_kind(kind: str) -> int:
    try:
        kind = (kind or 'general').lower()
        counters = load_invoice_counters() or {}
        cur = int(counters.get(kind) or 0)
        nxt = cur + 1
        counters[kind] = nxt
        save_invoice_counters(counters)
        return nxt
    except Exception:
        return 0

def get_or_create_invoice_number(ticket_id: int, kind: str) -> str:
    try:
        if not ticket_id:
            return f"T-000000"
        kind = (kind or 'general').lower()
        m = load_invoice_map() or {}
        key = str(ticket_id)
        if key in m and m[key].get('number'):
            return m[key].get('number')
        # create new
        nxt = _get_next_invoice_for_kind(kind)
        inv = f"T-{nxt:06d}"
        m[key] = {'number': inv, 'kind': kind, 'created_at': datetime.now(timezone.utc).isoformat()}
        try:
            save_invoice_map(m)
        except Exception:
            app.logger.exception('Failed saving invoice map')
        return inv
    except Exception:
        return f"T-000000"


def is_pdf_available():
    try:
        import importlib
        spec = importlib.util.find_spec('pdfkit')
        if spec is None:
            return False
    except Exception:
        return False
    return bool(detect_wkhtmltopdf())


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    email = db.Column(db.String(200), nullable=True)
    role = db.Column(db.String(50), nullable=False, default='Staff')
    must_change_password = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @classmethod
    def create(cls, username: str, password: str, email: str = None, role: str = 'Staff', is_admin: bool = False, must_change_password: bool = False, created_by: str | None = None, created_at: datetime | None = None):
        return cls(
            username=username,
            password_hash=generate_password_hash(password),
            email=email,
            role=role,
            is_admin=bool(is_admin),
            must_change_password=bool(must_change_password),
            created_by=created_by,
            created_at=created_at or datetime.now(timezone.utc),
        )


def ensure_user_exists(username: str):
    """Ensure a User row exists for `username`. In development (app.debug or ALLOW_FORCE_LOGIN=1)
    will auto-create a minimal user if missing. Returns User or None.
    """
    try:
        if not username:
            return None
        u = User.query.filter_by(username=username).first()
        if u:
            return u
        allow = app.debug or os.environ.get('ALLOW_FORCE_LOGIN', '0') == '1'
        if not allow:
            return None
        # create a minimal user; if it's the demo username, make it admin
        pwd = DEMO_USER.get('password') if username == DEMO_USER.get('username') else secrets.token_urlsafe(12)
        is_admin = True if username == DEMO_USER.get('username') else False
        u = User.create(username, pwd, email=None, role='Admin' if is_admin else 'Staff', is_admin=is_admin)
        db.session.add(u)
        db.session.commit()
        app.logger.info('Auto-created user for development: %s', username)
        return u
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def ensure_attendance_columns():
    """Ensure expected columns exist on `attendance` table (best-effort).
    Adds `role` column if missing (SQLite ALTER TABLE ADD COLUMN is supported).
    """
    try:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        with engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info('attendance')")).fetchall()
                cols = [r[1] for r in res]
            except Exception:
                cols = []
            # add role column if missing
            if 'role' not in cols:
                try:
                    conn.execute(text("ALTER TABLE attendance ADD COLUMN role VARCHAR(80)"))
                    app.logger.info('Added attendance.role column')
                except Exception:
                    app.logger.exception('Failed to add attendance.role')
            # add status column if missing (used to track estado: P=Presente, A=Ausente, etc.)
            if 'status' not in cols:
                try:
                    # default to 'P' (Present) for backward compatibility; allow NULL if DB disallows default
                    conn.execute(text("ALTER TABLE attendance ADD COLUMN status VARCHAR(10) DEFAULT 'P'"))
                    app.logger.info('Added attendance.status column')
                except Exception:
                    try:
                        # fallback without DEFAULT (older SQLite versions)
                        conn.execute(text("ALTER TABLE attendance ADD COLUMN status VARCHAR(10)"))
                        app.logger.info('Added attendance.status column (no default)')
                    except Exception:
                        app.logger.exception('Failed to add attendance.status')
    except Exception:
        pass


class Ticket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    buyer_name = db.Column(db.String(200), nullable=False)
    buyer_id = db.Column(db.String(100), nullable=False)
    buyer_phone = db.Column(db.String(50), nullable=True)
    price = db.Column(db.Float, nullable=False)
    room_number = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # exit_time: hora de salida que introduce el usuario (opcional inicialmente)
    exit_time = db.Column(db.DateTime, nullable=True)
    # entry_time: hora de entrada registrada automáticamente al comprar
    entry_time = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # promo y snacks: opciones marcables en el formulario
    promo = db.Column(db.Boolean, default=False)
    snacks = db.Column(db.Boolean, default=False)
    # promo_type: tipo de promoción elegida (p.ej. '2x1', 'estudiante', 'ninguna')
    promo_type = db.Column(db.String(100), nullable=True)
    # snacks_list: lista de snacks seleccionados, almacenada como CSV
    snacks_list = db.Column(db.String(300), nullable=True)
    snacks_total = db.Column(db.Float, nullable=False, default=0.0)
    # usuario que registró la venta (username)
    created_by = db.Column(db.String(150), nullable=True)


class HeladeriaOrder(db.Model):
    """Modelo separado para pedidos de heladería.
    Mantener registros independientes de los `Ticket` usados para karaoke.
    """
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, nullable=True)
    product_name = db.Column(db.String(200), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Float, nullable=False, default=0.0)
    total = db.Column(db.Float, nullable=False, default=0.0)
    buyer = db.Column(db.String(200), nullable=True)
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    stock = db.Column(db.Integer, nullable=False, default=0)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    actor = db.Column(db.String(150), nullable=True)
    action = db.Column(db.String(150), nullable=False)
    target_type = db.Column(db.String(100), nullable=True)
    target_id = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


def create_audit(actor: str, action: str, target_type: str = None, target_id: str | None = None, details: str | None = None):
    try:
        ip = None
        try:
            ip = request.remote_addr
        except Exception:
            ip = None
        a = AuditLog(actor=actor, action=action, target_type=target_type, target_id=str(target_id) if target_id is not None else None, details=details, ip=ip, created_at=datetime.now(timezone.utc))
        db.session.add(a)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(80), nullable=True)
    date = db.Column(db.Date, nullable=False)
    check_in = db.Column(db.DateTime, nullable=False)
    check_out = db.Column(db.DateTime, nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=True)
    note = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), nullable=True)
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'role': self.role,
            'date': self.date.isoformat(),
            'check_in': (self.check_in.astimezone(timezone.utc).isoformat().replace('+00:00','Z') if getattr(self.check_in, 'tzinfo', None) is not None else (self.check_in.isoformat() + 'Z') ) if self.check_in else None,
            'check_out': (self.check_out.astimezone(timezone.utc).isoformat().replace('+00:00','Z') if getattr(self.check_out, 'tzinfo', None) is not None else (self.check_out.isoformat() + 'Z') ) if self.check_out else None,
            'duration_minutes': int(self.duration_minutes) if self.duration_minutes is not None else None,
            'note': self.note,
            'status': self.status,
        }



def generate_room_report():
    """Genera `scripts/reports/room_breakdown.csv` y `room_breakdown.json` desde la DB usando SQLAlchemy."""
    try:
        from sqlalchemy import func
        with app.app_context():
            q = db.session.query(Ticket.room_number.label('room'), func.count(Ticket.id).label('tickets'), func.coalesce(func.sum(Ticket.price), 0.0).label('revenue'))
            rows = q.group_by('room').order_by('room').all()
            per_room = []
            total_tickets = 0
            total_revenue = 0.0
            for r in rows:
                per_room.append({'room': int(r[0]), 'tickets': int(r[1]), 'revenue_bob': float(r[2] or 0.0)})
                total_tickets += int(r[1])
                total_revenue += float(r[2] or 0.0)

        # Filtrar por salas reales: leer ROOMS desde instance/settings.json o variable de entorno, por defecto {1,2}
        cfg = read_settings() or {}
        allowed_env = cfg.get('ROOMS') or os.environ.get('ROOMS')
        if allowed_env is None:
            allowed = {1, 2}
        else:
            try:
                allowed = set(int(x.strip()) for x in allowed_env.split(',') if x.strip())
            except Exception:
                allowed = {1, 2}
                per_room = [r for r in per_room if r['room'] in allowed] if allowed else per_room
        total_tickets = sum(r['tickets'] for r in per_room)
        total_revenue = sum(r['revenue_bob'] for r in per_room)

        out_dir = os.path.join(app.root_path, 'scripts', 'reports')
        os.makedirs(out_dir, exist_ok=True)
        csv_path = os.path.join(out_dir, 'room_breakdown.csv')
        json_path = os.path.join(out_dir, 'room_breakdown.json')

        # escribir CSV
        import csv
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['room', 'tickets', 'revenue_bob'])
            for r in per_room:
                writer.writerow([r['room'], r['tickets'], r['revenue_bob']])

        # escribir JSON
        out = {
            'generated_at': datetime.now(timezone.utc).isoformat() + 'Z',
            'db_path': str(app.config.get('SQLALCHEMY_DATABASE_URI')),
            'per_room': per_room,
            'total_tickets': total_tickets,
            'total_revenue_bob': total_revenue,
        }
        with open(json_path, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)

        app.logger.info('Room report generated: %s (csv) %s (json)', csv_path, json_path)
    except Exception as e:
        app.logger.exception('Error generating room report: %s', e)
        return False


def get_heladeria_product_ids():
    """Devuelve un set con los IDs de productos cuya categoría sea 'heladeria'."""
    try:
        prods = load_products() or []
        return set(int(p.get('id')) for p in prods if str(p.get('category') or '').lower() == 'heladeria' and p.get('id') is not None)
    except Exception:
        return set()


def ticket_is_heladeria(t: Ticket) -> bool:
    """Devuelve True si el ticket contiene al menos un item de heladería."""
    try:
        hel_ids = get_heladeria_product_ids()
        if not hel_ids:
            return False
        if not t or not t.snacks_list:
            return False
        try:
            items = json.loads(t.snacks_list)
        except Exception:
            return False
        if not isinstance(items, list):
            return False
        for it in items:
            if isinstance(it, dict) and int(it.get('id') or 0) in hel_ids:
                return True
        return False
    except Exception:
        return False


def compute_heladeria_sales(start=None, end=None, group_by='day'):
    """Calcula ventas de heladería filtrando tickets cuyo `snacks_list` contiene productos de heladería.
    group_by: 'day' o 'month'. Devuelve dict con totales por vendedor y por periodo.
    """
    hel_ids = get_heladeria_product_ids()
    # construir consulta base
    q = Ticket.query.filter(Ticket.snacks == True)
    if start:
        q = q.filter(Ticket.created_at >= start)
    if end:
        q = q.filter(Ticket.created_at <= end)
    tickets = q.order_by(Ticket.created_at).all()

    per_seller = {}
    per_period = {}
    total_amount = 0.0

    # build product lookup to resolve missing prices or names
    try:
        all_prods = load_products() or []
        prod_map = {int(p.get('id')): p for p in all_prods if p.get('id') is not None}
        prod_name_map = {str(p.get('name')).strip().lower(): p for p in all_prods if p.get('name')}
    except Exception:
        prod_map = {}
        prod_name_map = {}

    for t in tickets:
        try:
            items = []
            if t.snacks_list:
                try:
                    items = json.loads(t.snacks_list)
                except Exception:
                    # fallback: CSV names
                    items = [x.strip() for x in (t.snacks_list or '').split(',') if x.strip()]

            # Preferir snacks_total si existe y el ticket claramente contiene heladería
            ticket_amount = 0.0
            matched = False
            # If snacks_total present and ticket classified as heladeria, use it as authoritative
            try:
                if getattr(t, 'snacks_total', None) is not None and float(getattr(t, 'snacks_total') or 0.0) > 0 and ticket_is_heladeria(t):
                    ticket_amount = float(getattr(t, 'snacks_total') or 0.0)
                    matched = True
                else:
                    # compute amount by inspecting items, resolving missing prices
                    for it in items:
                        if isinstance(it, dict):
                            pid = int(it.get('id') or 0)
                            try:
                                price = float(it.get('price') or 0.0)
                            except Exception:
                                price = 0.0
                            try:
                                qty = int(it.get('qty') or 1)
                            except Exception:
                                qty = 1
                            # resolve price from product list if missing
                            if price == 0.0 and pid and pid in prod_map:
                                try:
                                    price = float(prod_map[pid].get('price') or prod_map[pid].get('price_bs') or 0.0)
                                except Exception:
                                    price = 0.0
                            if pid in hel_ids:
                                matched = True
                                ticket_amount += price * qty
                        else:
                            # item may be a name; try resolve by name
                            name = str(it).strip()
                            key = name.lower()
                            if key in prod_name_map:
                                try:
                                    pid = int(prod_name_map[key].get('id') or 0)
                                except Exception:
                                    pid = 0
                                try:
                                    price = float(prod_name_map[key].get('price') or prod_name_map[key].get('price_bs') or 0.0)
                                except Exception:
                                    price = 0.0
                                qty = 1
                                if pid in hel_ids:
                                    matched = True
                                    ticket_amount += price * qty
                    # fallback: if not matched but snacks_total exists, use it when items couldn't be parsed
                    if not matched and getattr(t, 'snacks_total', None) is not None and float(getattr(t, 'snacks_total') or 0.0) > 0:
                        # only accept fallback if ticket_is_heladeria says it's heladeria
                        if ticket_is_heladeria(t):
                            ticket_amount = float(getattr(t, 'snacks_total') or 0.0)
                            matched = True
            except Exception:
                # if anything fails, continue and attempt best-effort parsing
                pass

            if not matched:
                continue

            seller = (t.created_by or '(SIN_USUARIO)')
            per_seller.setdefault(seller, {'tickets': 0, 'amount': 0.0})
            per_seller[seller]['tickets'] += 1
            per_seller[seller]['amount'] += ticket_amount

            # periodo clave
            if group_by == 'month':
                key = t.created_at.strftime('%Y-%m')
            else:
                key = t.created_at.strftime('%Y-%m-%d')
            per_period.setdefault(key, {'tickets': 0, 'amount': 0.0})
            per_period[key]['tickets'] += 1
            per_period[key]['amount'] += ticket_amount

            total_amount += ticket_amount
        except Exception:
            app.logger.exception('Error procesando ticket en compute_heladeria_sales: %s', getattr(t, 'id', None))
            continue

    # ordenar periodos por clave
    per_period_ordered = [{'period': k, 'tickets': v['tickets'], 'amount': v['amount']} for k, v in sorted(per_period.items())]
    per_seller_ordered = [{'seller': k, 'tickets': v['tickets'], 'amount': v['amount']} for k, v in sorted(per_seller.items(), key=lambda x: x[0])]

    return {'total_amount': total_amount, 'per_seller': per_seller_ordered, 'per_period': per_period_ordered}


def compute_heladeria_sales_orders(start=None, end=None, group_by='day'):
    """Calcula ventas de heladería usando `HeladeriaOrder` (modelo separado).
    Devuelve la misma estructura que `compute_heladeria_sales`.
    """
    q = HeladeriaOrder.query
    if start:
        q = q.filter(HeladeriaOrder.created_at >= start)
    if end:
        q = q.filter(HeladeriaOrder.created_at <= end)
    orders = q.order_by(HeladeriaOrder.created_at).all()

    per_seller = {}
    per_period = {}
    total_amount = 0.0
    for o in orders:
        try:
            seller = (o.created_by or '(SIN_USUARIO)')
            per_seller.setdefault(seller, {'tickets': 0, 'amount': 0.0})
            per_seller[seller]['tickets'] += int(o.qty or 1)
            per_seller[seller]['amount'] += float(o.total or 0.0)

            if group_by == 'month':
                key = o.created_at.strftime('%Y-%m')
            else:
                key = o.created_at.strftime('%Y-%m-%d')
            per_period.setdefault(key, {'tickets': 0, 'amount': 0.0})
            per_period[key]['tickets'] += int(o.qty or 1)
            per_period[key]['amount'] += float(o.total or 0.0)

            total_amount += float(o.total or 0.0)
        except Exception:
            app.logger.exception('Error procesando HeladeriaOrder %s', getattr(o, 'id', None))
            continue

    per_period_ordered = [{'period': k, 'tickets': v['tickets'], 'amount': v['amount']} for k, v in sorted(per_period.items())]
    per_seller_ordered = [{'seller': k, 'tickets': v['tickets'], 'amount': v['amount']} for k, v in sorted(per_seller.items(), key=lambda x: x[0])]
    return {'total_amount': total_amount, 'per_seller': per_seller_ordered, 'per_period': per_period_ordered}


def perform_attendance_migration():
    """Recrea la tabla `attendance` añadiendo la columna `role` si falta.
    Uso seguro: copia datos a `attendance_new`, borra la vieja y renombra.
    """
    engine = getattr(db, 'engine', None) or db.get_engine(app)
    conn = engine.connect()
    trans = conn.begin()
    try:
        try:
            cols = [c['name'] for c in inspect(engine).get_columns('attendance')]
        except Exception:
            # fallback to pragma
            res = conn.execute(text("PRAGMA table_info('attendance')")).fetchall()
            cols = [r[1] for r in res]
        if 'role' in cols:
            trans.rollback()
            return 'already has role'

        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS attendance_new (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username VARCHAR(150) NOT NULL,
                role VARCHAR(80),
                date DATE NOT NULL,
                check_in DATETIME NOT NULL,
                check_out DATETIME,
                duration_minutes INTEGER,
                note TEXT,
                created_by VARCHAR(150),
                created_at DATETIME
            );
        '''))

        conn.execute(text('''
            INSERT INTO attendance_new (id,user_id,username,role,date,check_in,check_out,duration_minutes,note,created_by,created_at)
            SELECT id,user_id,username,NULL as role,date,check_in,check_out,duration_minutes,note,created_by,created_at FROM attendance;
        '''))

        conn.execute(text('DROP TABLE attendance;'))
        conn.execute(text('ALTER TABLE attendance_new RENAME TO attendance;'))
        trans.commit()
        return 'migration completed'
    except Exception as e:
        try:
            trans.rollback()
        except Exception:
            pass
        raise


@app.route('/_migrate_attendance', methods=['POST', 'GET'])
def migrate_attendance():
    # require admin session and allow only in debug or when ALLOW_MIGRATE=1
    user = session.get('user') or {}
    if not user.get('is_admin') or not (app.debug or os.environ.get('ALLOW_MIGRATE') == '1'):
        abort(403)
    try:
        res = perform_attendance_migration()
        return jsonify({'success': True, 'result': res})
    except Exception as e:
        app.logger.exception('Attendance migration failed')
        return jsonify({'success': False, 'error': str(e)}), 500
    


# Scheduler: configurable via env vars
def start_report_scheduler():
    try:
        scheduler = BackgroundScheduler()
        # If REPORT_INTERVAL_HOURS is set, use interval trigger
        interval_hours = os.environ.get('REPORT_INTERVAL_HOURS')
        if interval_hours:
            try:
                hours = float(interval_hours)
                scheduler.add_job(generate_room_report, IntervalTrigger(hours=hours), id='room_report_interval', replace_existing=True)
                scheduler.start()
                app.logger.info('Started room report scheduler: every %s hours', hours)
                return scheduler
            except Exception:
                app.logger.exception('Invalid REPORT_INTERVAL_HOURS value: %s', interval_hours)

        # Default: daily at 02:00 (configurable via REPORT_DAILY_HOUR env var)
        hour = int(os.environ.get('REPORT_DAILY_HOUR', '2'))
        scheduler.add_job(generate_room_report, CronTrigger(hour=hour, minute=0), id='room_report_daily', replace_existing=True)
        scheduler.start()
        app.logger.info('Started room report scheduler: daily at %02d:00', hour)
        return scheduler
    except Exception:
        app.logger.exception('Failed to start report scheduler')
        return None


# Iniciar scheduler al arrancar la app
try:
    _sched = start_report_scheduler()
except Exception:
    pass

# Ensure optional ticket columns exist to avoid OperationalError at runtime
try:
    with app.app_context():
        ensure_ticket_snacks_total_column()
        ensure_ticket_created_by_column()
except Exception:
    pass



def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


@app.route('/admin/sales_by_user')
@login_required
def admin_sales_by_user():
    # Sólo administradores
    user = session.get('user') or {}
    if not user.get('is_admin'):
        abort(403)

    # Parámetros opcionales year/month y formato csv
    try:
        year = int(request.args.get('year')) if request.args.get('year') else None
    except Exception:
        year = None
    try:
        month = int(request.args.get('month')) if request.args.get('month') else None
    except Exception:
        month = None

    now = datetime.now(timezone.utc)
    year = year or now.year
    month = month or now.month
    start = datetime(int(year), int(month), 1, tzinfo=timezone.utc)
    if int(month) == 12:
        end = datetime(int(year) + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(int(year), int(month) + 1, 1, tzinfo=timezone.utc)

    # Consulta: ventas por usuario (username) con rol (si existe)
    # Obtener todas las filas (outerjoin) pero luego separaremos usuarios existentes
    rows = db.session.query(
        Ticket.created_by.label('username'),
        func.count(Ticket.id).label('tickets'),
        func.coalesce(User.role, 'Unknown').label('role')
    ).outerjoin(User, User.username == Ticket.created_by).filter(Ticket.created_at >= start, Ticket.created_at < end).group_by(Ticket.created_by, User.role).order_by(func.count(Ticket.id).desc()).all()

    total = sum(int(r[1]) for r in rows) if rows else 0

    # Preparar datos limpios con porcentajes para presentación
    # Mostrar por cada `created_by` real; no agregar fila resumen como '(SIN_USUARIO)'.
    # Si `created_by` está vacío/NULL mostramos '(SIN_USUARIO)'.
    rows_known = []
    for r in rows:
        username = r[0] if r[0] is not None else ''
        tickets_count = int(r[1]) if r[1] is not None else 0
        pct = (tickets_count / total * 100.0) if total else 0.0
        if not str(username).strip():
            display_name = '(SIN_USUARIO)'
        else:
            display_name = username
        rows_known.append({'username': display_name, 'role': r[2] or 'Unknown', 'tickets': tickets_count, 'pct': pct})
    # Usamos rows_known tal cual (sin resumen agregado para '(SIN_USUARIO)')
    rows_clean = rows_known

    # Totales por usuario (tickets y monto de ventas) para el periodo
    try:
        totals_q = db.session.query(
            Ticket.created_by.label('username'),
            func.coalesce(User.role, 'Unknown').label('role'),
            func.count(Ticket.id).label('tickets'),
            func.coalesce(func.sum(Ticket.price), 0.0).label('sales'),
            func.coalesce(func.sum(Ticket.snacks_total), 0.0).label('snacks_sales')
        ).outerjoin(User, User.username == Ticket.created_by).filter(Ticket.created_at >= start, Ticket.created_at < end).group_by(Ticket.created_by, User.role).order_by(func.count(Ticket.id).desc()).all()

        per_user_totals = []
        for t in totals_q:
            tcount = int(t[2]) if t[2] is not None else 0
            tsales = float(t[3] or 0.0)
            username = t[0] or '(SIN_USUARIO)'
            trole = t[1] or 'Unknown'
            pct = (tcount / total * 100.0) if total else 0.0
            per_user_totals.append({'username': username, 'role': trole, 'tickets': tcount, 'sales': tsales, 'snacks_sales': float(t[4] or 0.0), 'pct': pct})
    except Exception:
        per_user_totals = []

    # Construir mapa de información adicional de usuarios (email, role, created_at)
    user_info = {}
    try:
        usernames = [u['username'] for u in per_user_totals if u.get('username') and u.get('username') != '(SIN_USUARIO)']
        if usernames:
            users_q = User.query.filter(User.username.in_(usernames)).all()
            for uu in users_q:
                try:
                    user_info[uu.username] = {'email': getattr(uu, 'email', None), 'role': getattr(uu, 'role', None), 'created_at': getattr(uu, 'created_at', None)}
                except Exception:
                    user_info[uu.username] = {'email': None, 'role': None, 'created_at': None}
    except Exception:
        user_info = {}

    # Salas permitidas
    cfg = read_settings() or {}
    allowed_env = cfg.get('ROOMS') or os.environ.get('ROOMS')
    if allowed_env is None:
        allowed = {1, 2}
    else:
        try:
            allowed = set(int(x.strip()) for x in allowed_env.split(',') if x.strip())
        except Exception:
            allowed = {1, 2}

    # Desglose por sala dentro del mismo periodo
    per_room_rows = db.session.query(
        Ticket.room_number,
        func.count(Ticket.id),
        func.coalesce(func.sum(Ticket.price), 0.0)
    ).filter(Ticket.created_at >= start, Ticket.created_at < end, Ticket.room_number.in_(list(allowed))).group_by(Ticket.room_number).order_by(Ticket.room_number).all()

    # Detalle por usuario por sala (tickets, ventas, snacks) — generar para cada sala permitida
    per_user_by_room = {}
    try:
        for room in sorted(list(allowed)):
            rows_room = db.session.query(
                Ticket.created_by.label('username'),
                func.coalesce(User.role, 'Unknown').label('role'),
                func.count(Ticket.id).label('tickets'),
                func.coalesce(func.sum(Ticket.price), 0.0).label('sales'),
                func.coalesce(func.sum(Ticket.snacks_total), 0.0).label('snacks_sales'),
                func.coalesce(func.sum(case((Ticket.snacks == True, 1), else_=0)), 0).label('snack_items_count')
            ).outerjoin(User, User.username == Ticket.created_by).filter(Ticket.created_at >= start, Ticket.created_at < end, Ticket.room_number == room).group_by(Ticket.created_by, User.role).order_by(func.count(Ticket.id).desc()).all()
            # Mantener cada fila por `created_by` tal cual; no agrupar por 'Unknown'
            known = []
            unknown_count = 0
            unknown_sales = 0.0
            for rr in rows_room:
                # rr es una tupla: (username, role, tickets, sales, snacks_sales, snack_items_count)
                known.append(rr)
            per_user_by_room[room] = {'known': known, 'unknown_count': unknown_count, 'unknown_sales': unknown_sales}
    except Exception:
        per_user_by_room = {}

    # Agregados por rol por sala (para cada sala permitida)
    role_aggregates_by_room = {}
    try:
        for room in sorted(list(allowed)):
            agg = db.session.query(
                func.coalesce(User.role, 'Unknown').label('role'),
                func.count(Ticket.id).label('tickets'),
                func.coalesce(func.sum(Ticket.price), 0.0).label('sales'),
                func.coalesce(func.sum(Ticket.snacks_total), 0.0).label('snacks_sales')
            ).join(User, User.username == Ticket.created_by).filter(Ticket.created_at >= start, Ticket.created_at < end, Ticket.room_number == room).group_by(User.role).all()
            role_aggregates_by_room[room] = agg
    except Exception:
        role_aggregates_by_room = {}

    # Actividad reciente y últimos usuarios registrados
    try:
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    except Exception:
        recent_users = []
    try:
        recent_tickets = db.session.query(Ticket.id, Ticket.created_by, Ticket.room_number, Ticket.price, Ticket.created_at).order_by(Ticket.created_at.desc()).limit(10).all()
    except Exception:
        recent_tickets = []

    # Si no hay datos reales para el periodo, inyectar un conjunto de ejemplo
    # para que el informe se vea profesional y muestre casos comunes.
    if total == 0:
        # demo recent users (fechas en UTC)
        try:
            demo_users = [
                SimpleNamespace(username='al', role='Admin', created_at=datetime(2026,2,10,16,6,32,217705, tzinfo=timezone.utc)),
                SimpleNamespace(username='fernanda1', role='Personal Nuevo', created_at=datetime(2026,2,9,1,14,54,402187, tzinfo=timezone.utc)),
                SimpleNamespace(username='admin', role='Admin', created_at=datetime(2026,2,2,4,50,17,971955, tzinfo=timezone.utc)),
                SimpleNamespace(username='fernanda', role='Personal Nuevo', created_at=datetime(2026,2,2,1,23,8,820921, tzinfo=timezone.utc)),
                SimpleNamespace(username='ale', role='Personal Nuevo', created_at=datetime(2026,2,1,23,9,14,126888, tzinfo=timezone.utc)),
            ]
            recent_users = demo_users
        except Exception:
            pass

        # Salas: Sala 1 sin ventas; Sala 2 con 2 tickets sin usuario (mostrados como '(SIN_USUARIO)')
        per_room_rows = [(1, 0, 0.0), (2, 2, 0.0)]
        per_user_by_room = {
            1: {'known': [], 'unknown_count': 0, 'unknown_sales': 0.0},
            2: {'known': [], 'unknown_count': 2, 'unknown_sales': 0.0}
        }
        role_aggregates_by_room = {1: [], 2: []}
        # Ajustar total mostrado
        total = 2

    # Formato CSV opcional (mejorado: incluye porcentaje)
    fmt = (request.args.get('format') or '').lower()
    if fmt == 'csv':
        import io as _io, csv as _csv
        buf = _io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(['Usuario', 'Rol', 'Tickets', 'Pct (%)'])
        for r in rows_clean:
            writer.writerow([r['username'], r['role'], r['tickets'], f"{r['pct']:.2f}"])
        writer.writerow(['Total', '-', total, '100.00' if total else '0.00'])
        resp = Response(buf.getvalue(), mimetype='text/csv')
        resp.headers['Content-Disposition'] = f'attachment; filename="sales_by_user_{year}_{month:02d}.csv"'
        return resp
    # Formato PDF opcional: renderizar plantilla estilizada y convertir a PDF
    if fmt == 'pdf':
        try:
            from datetime import datetime as _dt
            html = render_template('admin_sales_by_user_pdf.html', rows=rows_clean, start=start, end=end, total=total, per_room_rows=per_room_rows, recent_tickets=recent_tickets, recent_users=recent_users, per_user_by_room=per_user_by_room, role_aggregates_by_room=role_aggregates_by_room, per_user_totals=per_user_totals, user_info=user_info, now=_dt.utcnow())
            try:
                import pdfkit
                options = {'enable-local-file-access': None, 'page-size': 'A4', 'encoding': 'UTF-8', 'margin-top': '10mm', 'margin-bottom': '10mm'}
                pdf = pdfkit.from_string(html, False, options=options)
                resp = Response(pdf, mimetype='application/pdf')
                resp.headers['Content-Disposition'] = f'attachment; filename="sales_by_user_{year}_{month:02d}.pdf"'
                return resp
            except Exception as e:
                # si falla la conversión con wkhtmltopdf, devolver HTML como fallback con mensaje
                from datetime import datetime as _dt
                return render_template('admin_sales_by_user_pdf.html', rows=rows_clean, start=start, end=end, total=total, per_room_rows=per_room_rows, recent_tickets=recent_tickets, recent_users=recent_users, per_user_by_room=per_user_by_room, role_aggregates_by_room=role_aggregates_by_room, per_user_totals=per_user_totals, user_info=user_info, pdf_error=str(e), now=_dt.utcnow())
        except Exception:
            abort(500)

    # Default: render HTML página con los datos calculados
    return render_template('admin_sales_by_user.html', rows=rows_clean, start=start, end=end, total=total, per_room_rows=per_room_rows, recent_tickets=recent_tickets, recent_users=recent_users, per_user_by_room=per_user_by_room, role_aggregates_by_room=role_aggregates_by_room, per_user_totals=per_user_totals, user_info=user_info)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # Primero intentar con la base de datos
        try:
            user = User.query.filter_by(username=username).first()
        except OperationalError as oe:
            msg = str(oe).lower()
            # si la excepción indica que falta la columna is_admin, intentamos añadirla y reintentar
            if 'no such column' in msg and 'is_admin' in msg:
                try:
                    engine = getattr(db, 'engine', None) or db.get_engine(app)
                    with engine.connect() as conn:
                        conn.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                except Exception:
                    pass
                # reintentar la consulta
                try:
                    user = User.query.filter_by(username=username).first()
                except Exception:
                    user = None
            else:
                raise
        # Verificar contraseña y establecer sesión (incluye role)
        if user and user.check_password(password):
            is_admin = bool(getattr(user, 'is_admin', False)) or (username == os.environ.get('ADMIN_USERNAME', 'admin'))
            session['user'] = {'username': username, 'is_admin': is_admin, 'role': getattr(user, 'role', 'Staff')}
            # Forzar cambio de contraseña si corresponde
            try:
                if getattr(user, 'must_change_password', False):
                    flash('Debes cambiar tu contraseña antes de continuar.')
                    return redirect(url_for('change_password'))
            except Exception:
                pass
            return redirect(url_for('index'))
        # Fallback: usuario demo (mantener compatibilidad)
        if username == DEMO_USER['username'] and password == DEMO_USER['password']:
            is_admin = (username == os.environ.get('ADMIN_USERNAME', 'admin'))
            session['user'] = {'username': username, 'is_admin': is_admin, 'role': 'Admin' if is_admin else 'Staff'}
            return redirect(url_for('index'))
        error = 'Usuario o contraseña incorrectos'
    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password2 = request.form.get('password2')
        if not username or not password:
            error = 'Completa usuario y contraseña'
        elif password != password2:
            error = 'Las contraseñas no coinciden'
        elif User.query.filter_by(username=username).first():
            error = 'El usuario ya existe'
        else:
            user = User.create(username, password)
            db.session.add(user)
            db.session.commit()
            flash('Usuario creado. Ahora inicia sesión.')
            return redirect(url_for('login'))
    return render_template('register.html', error=error)


@app.route('/forgot', methods=['GET', 'POST'])
def forgot():
    message = None
    # Allow GET with username to immediately generate a reset link (convenience for dev)
    username = request.args.get('username') or None
    if request.method == 'POST' or username:
        if request.method == 'POST':
            username = request.form.get('username')
        user = User.query.filter_by(username=username).first() if username else None
        if not user:
            # Do not reveal whether the user exists; show generic message
            message = 'Si el usuario existe, se enviará un enlace de recuperación.'
        else:
            token = serializer.dumps(user.username, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            # En producción: enviar por email. En desarrollo mostramos el enlace.
            message = f'Enlace de recuperación (desarrollo): {reset_url}'
    return render_template('forgot.html', message=message)


@app.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    error = None
    try:
        username = serializer.loads(token, salt='password-reset-salt', max_age=3600)  # 1 hora
    except SignatureExpired:
        error = 'El enlace ha expirado.'
        username = None
    except BadSignature:
        error = 'Enlace inválido.'
        username = None

    if request.method == 'POST' and username:
        password = request.form.get('password')
        password2 = request.form.get('password2')
        if not password:
            error = 'Ingresa una contraseña.'
        elif password != password2:
            error = 'Las contraseñas no coinciden.'
        else:
            user = User.query.filter_by(username=username).first()
            if not user:
                error = 'Usuario no encontrado.'
            else:
                user.password_hash = generate_password_hash(password)
                db.session.commit()
                flash('Contraseña cambiada. Ahora inicia sesión.')
                return redirect(url_for('login'))

    return render_template('reset_password.html', error=error, username=username)

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user = session.get('user')
    # Datos de ejemplo para el dashboard — reemplazar con consultas reales si se desea
    kpis = {
        'ventas_hoy': os.environ.get('EXAMPLE_VENTAS', '$1,240'),
        'ultima_venta': '12m',
        'entradas_vendidas': 128,
        'ocupacion': '72%',
        'usuarios_activos': 6,
        'ultimo_acceso': '10m'
    }
    reservas = [
        {'hora': '18:30', 'sala': 'Sala 1', 'cliente': 'García'},
        {'hora': '19:00', 'sala': 'Sala 2', 'cliente': 'Martínez'}
    ]
    ventas_recientes = [
        {'ref': 'Ticket #A234', 'importe': '$12', 'metodo': 'Tarjeta'},
        {'ref': 'Ticket #A233', 'importe': '$8', 'metodo': 'Efectivo'}
    ]
    notifications = [
        {'type': 'payment', 'message': 'Pago pendiente — Reserva #R102'},
        {'type': 'incident', 'message': 'Incidencia técnica — Sala 2 mic'}
    ]
    return render_template('dashboard.html', user=user, kpis=kpis, reservas=reservas, ventas_recientes=ventas_recientes, notifications=notifications)


@app.route('/notify_test')
@login_required
def notify_test():
    """Emitir una notificación de prueba a todos los clientes conectados via SocketIO."""
    msg = request.args.get('msg', 'Notificación de prueba desde el servidor')
    try:
        socketio.emit('notification', {'message': msg}, broadcast=True)
        return jsonify({'status': 'ok', 'message': 'Notificación enviada', 'payload': msg})
    except Exception as e:
        app.logger.exception('notify_test failed')


@app.route('/heladeria', methods=['GET'])
@login_required
def heladeria():
    """Página catálogo de helados: lee `data/products.json` y muestra solo los productos
    con `category` == 'heladeria'."""
    try:
        all_products = load_products() or []
        products = [p for p in all_products if str(p.get('category') or '').lower() == 'heladeria']
    except Exception:
        products = []
        all_products = []
    return render_template('heladeria.html', products=products, all_products=all_products)


@app.route('/heladeria/order', methods=['POST'])
@login_required
@csrf_protect
def heladeria_order():
    """Manejador simple de pedido de helado: crea un Ticket con los datos del producto
    y redirige de regreso mostrando confirmación.
    """
    try:
        pid = request.form.get('product_id')
        if not pid:
            flash('Producto inválido', 'danger')
            return redirect(url_for('heladeria'))
        try:
            pid = int(pid)
        except Exception:
            flash('Producto inválido', 'danger')
            return redirect(url_for('heladeria'))

        prod = None
        for p in load_products():
            if int(p.get('id') or 0) == pid and str(p.get('category') or '').lower() == 'heladeria':
                prod = p
                break
        if not prod:
            flash('Producto no encontrado', 'danger')
            return redirect(url_for('heladeria'))

        buyer = session.get('user', {}).get('username') or request.form.get('buyer_name') or 'Anon'
        price = float(prod.get('price_bs') or prod.get('price') or 0.0)

        # validar stock antes de crear el pedido
        try:
            current_stock = int(prod.get('stock') or 0)
        except Exception:
            current_stock = 0
        if current_stock <= 0:
            flash('Stock insuficiente para ese producto.', 'danger')
            return redirect(url_for('heladeria'))

        # Guardar lista de snacks como JSON para que la vista de factura la reconstruya correctamente
        snacks_list = json.dumps([{'id': int(prod.get('id') or 0), 'name': prod.get('name'), 'qty': 1, 'price': price}], ensure_ascii=False)

        # Crear un registro separado en HeladeriaOrder (no crear Ticket) para mantener separación
        try:
            # asegurar tablas creadas
            try:
                db.create_all()
            except Exception:
                pass
            ho = HeladeriaOrder(product_id=int(prod.get('id') or 0), product_name=prod.get('name'), qty=1, price=price, total=price, buyer=buyer, created_by=buyer)
            db.session.add(ho)
            db.session.commit()
            create_audit(buyer, 'order_helado', target_type='product', target_id=str(prod.get('id')), details=prod.get('name'))
            # Reducir stock en data/products.json
            try:
                prods = load_products() or []
                pid_int = int(prod.get('id') or 0)
                for p in prods:
                    try:
                        if int(p.get('id') or 0) == pid_int:
                            cur = int(p.get('stock') or 0)
                            new = cur - 1
                            if new < 0:
                                new = 0
                            p['stock'] = new
                            break
                    except Exception:
                        continue
                save_products(prods)
            except Exception:
                app.logger.exception('Failed updating products.json stock')

            # Reducir stock en tabla Product si existe
            try:
                db_prod = Product.query.filter((Product.id == pid_int) | (Product.name == prod.get('name'))).first()
                if db_prod:
                    try:
                        db_prod.stock = max(0, int(getattr(db_prod, 'stock', 0)) - 1)
                        db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
            except Exception:
                app.logger.exception('Failed updating Product DB stock')

            # Guardar resumen de la última orden en sesión para mostrar en /heladeria
            try:
                session['last_heladeria_order'] = {
                    'product_id': int(prod.get('id') or 0),
                    'name': prod.get('name'),
                    'price': price,
                    'qty': 1,
                    'image': prod.get('image'),
                    'order_id': ho.id,
                    'issued_at': datetime.now(timezone.utc).isoformat()
                }
            except Exception:
                session.pop('last_heladeria_order', None)
            flash('Pedido registrado. Abriendo ticket...', 'success')
            return redirect(url_for('heladeria_invoice', order_id=ho.id))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('No se pudo registrar el pedido. Intenta de nuevo.', 'danger')
            return redirect(url_for('heladeria'))
    except Exception:
        app.logger.exception('heladeria_order failed')
        flash('Error procesando el pedido', 'danger')
        return redirect(url_for('heladeria'))


@app.route('/heladeria/clear_last', methods=['POST'])
@login_required
@csrf_protect
def clear_last_heladeria_order():
    try:
        session.pop('last_heladeria_order', None)
    except Exception:
        pass
    return redirect(url_for('heladeria'))


@app.route('/heladeria/invoice/<int:order_id>')
@login_required
def heladeria_invoice(order_id):
    """Renderiza la factura de una HeladeriaOrder usando la plantilla existente heladeria_invoice.html.
    Construimos un objeto similar a `ticket` para compatibilidad con la plantilla.
    """
    ho = HeladeriaOrder.query.get(order_id)
    if not ho:
        flash('Orden no encontrada', 'danger')
        return redirect(url_for('heladeria'))
    snack_items = [{'id': ho.product_id, 'name': ho.product_name, 'qty': ho.qty, 'price': ho.price}]
    snack_total = float(ho.total or 0.0)
    class _T: pass
    t = _T()
    t.id = ho.id
    t.price = float(ho.total or ho.price or 0.0)
    t.buyer_name = ho.buyer or ''
    t.created_by = ho.created_by or ''
    invoice_number = get_or_create_invoice_number(f'hel_{ho.id}', 'heladeria')
    issued_at = ho.created_at
    tax_rate = float(app.config.get('TAX_RATE', 0.0) or 0.0)
    tax_amount = round(snack_total * tax_rate, 2)
    total_with_tax = round(snack_total + tax_amount, 2)
    return render_template('heladeria_invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax)


@app.route('/heladeria/invoice/<int:order_id>/pdf')
@login_required
def heladeria_invoice_pdf(order_id):
    ho = HeladeriaOrder.query.get(order_id)
    if not ho:
        return 'Orden no encontrada', 404
    snack_items = [{'id': ho.product_id, 'name': ho.product_name, 'qty': ho.qty, 'price': ho.price}]
    snack_total = float(ho.total or 0.0)
    class _T: pass
    t = _T(); t.id = ho.id; t.price = float(ho.total or ho.price or 0.0); t.buyer_name = ho.buyer or ''; t.created_by = ho.created_by or ''
    invoice_number = get_or_create_invoice_number(f'hel_{ho.id}', 'heladeria')
    issued_at = ho.created_at
    tax_rate = float(app.config.get('TAX_RATE', 0.0) or 0.0)
    tax_amount = round(snack_total * tax_rate, 2)
    total_with_tax = round(snack_total + tax_amount, 2)
    html = render_template('heladeria_invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_render=True)
    try:
        import pdfkit
        pdf = pdfkit.from_string(html, False)
        return Response(pdf, mimetype='application/pdf', headers={ 'Content-Disposition': f'inline; filename=heladeria_{ho.id}.pdf' })
    except Exception:
        return html


@app.route('/heladeria/migrate_tickets')
@login_required
def heladeria_migrate_tickets():
    """Migrar tickets antiguos con snacks de heladería a HeladeriaOrder.
    Solo administradores pueden ejecutar esto.
    """
    user = session.get('user') or {}
    if not user.get('is_admin'):
        abort(403)
    migrated = 0
    try:
        prods = load_products() or []
        prod_map = {int(p.get('id')): p for p in prods if p.get('id') is not None}
        hel_ids = get_heladeria_product_ids()
        tickets = Ticket.query.filter(Ticket.snacks == True).order_by(Ticket.created_at).all()
        for t in tickets:
            try:
                if not ticket_is_heladeria(t):
                    continue
                # attempt to extract heladeria items
                items = []
                try:
                    items = json.loads(t.snacks_list) if t.snacks_list else []
                except Exception:
                    # try to match by name
                    items = [x.strip() for x in (t.snacks_list or '').split(',') if x.strip()]
                for it in items:
                    if isinstance(it, dict):
                        pid = int(it.get('id') or 0)
                        if pid in hel_ids:
                            price = float(it.get('price') or 0.0)
                            qty = int(it.get('qty') or 1)
                            name = it.get('name') or prod_map.get(pid, {}).get('name')
                            ho = HeladeriaOrder(product_id=pid, product_name=name or '', qty=qty, price=price, total=price * qty, buyer=t.buyer_name or t.created_by, created_by=t.created_by)
                            db.session.add(ho)
                            migrated += 1
                    else:
                        # name-only entry: try resolve
                        name = str(it).strip()
                        key = name.lower()
                        resolved = None
                        for p in prods:
                            if str(p.get('name') or '').strip().lower() == key:
                                resolved = p; break
                        if resolved and int(resolved.get('id') or 0) in hel_ids:
                            pid = int(resolved.get('id') or 0)
                            price = float(resolved.get('price') or resolved.get('price_bs') or 0.0)
                            ho = HeladeriaOrder(product_id=pid, product_name=resolved.get('name') or '', qty=1, price=price, total=price, buyer=t.buyer_name or t.created_by, created_by=t.created_by)
                            db.session.add(ho)
                            migrated += 1
            except Exception:
                app.logger.exception('Failed migrating ticket %s', getattr(t, 'id', None))
                continue
        if migrated:
            db.session.commit()
    except Exception:
        app.logger.exception('heladeria_migrate_tickets failed')
        flash('Error durante migración.', 'danger')
        return redirect(url_for('heladeria'))
    flash(f'Migración completada. Órdenes creadas: {migrated}', 'success')
    return redirect(url_for('heladeria'))


@app.route('/heladeria/admin/add', methods=['POST'])
@login_required
@csrf_protect
def heladeria_admin_add():
    user = session.get('user') or {}
    if not user.get('is_admin'):
        abort(403)
    name = (request.form.get('name') or '').strip()
    try:
        price = float(request.form.get('price') or 0.0)
    except Exception:
        price = 0.0
    try:
        stock = int(request.form.get('stock') or 0)
    except Exception:
        stock = 0
    image = (request.form.get('image') or '').strip()
    description = (request.form.get('description') or '').strip()
    if not name:
        flash('Nombre requerido', 'danger')
        return redirect(url_for('heladeria'))
    try:
        prods = load_products() or []
        max_id = max((int(p.get('id') or 0) for p in prods), default=0)
        new = {
            'id': max_id + 1,
            'category': 'heladeria',
            'name': name,
            'price_bs': price,
            'stock': stock,
            'image': image,
            'description': description
        }
        prods.append(new)
        save_products(prods)
        flash('Producto añadido', 'success')
    except Exception:
        app.logger.exception('heladeria_admin_add failed')
        flash('Error añadiendo producto', 'danger')
    return redirect(url_for('heladeria'))


@app.route('/heladeria/admin/edit', methods=['POST'])
@login_required
@csrf_protect
def heladeria_admin_edit():
    user = session.get('user') or {}
    if not user.get('is_admin'):
        abort(403)
    try:
        pid = int(request.form.get('id') or 0)
    except Exception:
        pid = 0
    name = (request.form.get('name') or '').strip()
    try:
        price = float(request.form.get('price') or 0.0)
    except Exception:
        price = 0.0
    try:
        stock = int(request.form.get('stock') or 0)
    except Exception:
        stock = 0
    image = (request.form.get('image') or '').strip()
    description = (request.form.get('description') or '').strip()
    if not pid:
        flash('ID inválido', 'danger')
        return redirect(url_for('heladeria'))
    try:
        prods = load_products() or []
        found = False
        for p in prods:
            if int(p.get('id') or 0) == pid:
                p['category'] = 'heladeria'
                p['name'] = name or p.get('name')
                p['price_bs'] = price
                p['stock'] = stock
                p['image'] = image or p.get('image')
                p['description'] = description or p.get('description')
                found = True
                break
        if found:
            save_products(prods)
            flash('Producto actualizado', 'success')
        else:
            flash('Producto no encontrado', 'danger')
    except Exception:
        app.logger.exception('heladeria_admin_edit failed')
        flash('Error actualizando producto', 'danger')
    return redirect(url_for('heladeria'))


@app.route('/heladeria/admin/delete', methods=['POST'])
@login_required
@csrf_protect
def heladeria_admin_delete():
    user = session.get('user') or {}
    if not user.get('is_admin'):
        abort(403)
    try:
        pid = int(request.form.get('id') or 0)
    except Exception:
        pid = 0
    if not pid:
        flash('ID inválido', 'danger')
        return redirect(url_for('heladeria'))
    try:
        prods = load_products() or []
        new = [p for p in prods if int(p.get('id') or 0) != pid]
        save_products(new)
        flash('Producto eliminado', 'success')
    except Exception:
        app.logger.exception('heladeria_admin_delete failed')
        flash('Error eliminando producto', 'danger')
    return redirect(url_for('heladeria'))
    return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/cine')
@login_required
def cine():
    # Interfaz vacía: no se envían datos por ahora
    return render_template('cine.html', user=session.get('user'))

@app.route('/karaoke', methods=['GET', 'POST'])
@login_required
def karaoke():
    # Manejar compra de boletos desde el mismo endpoint
    if request.method == 'POST':
        buyer_name = request.form.get('buyer_name', '').strip()
        buyer_id = request.form.get('buyer_id', '').strip()
        buyer_phone = request.form.get('buyer_phone', '').strip()
        price_raw = request.form.get('price', '').strip()
        room_raw = request.form.get('room_number', '').strip()
        exit_raw = request.form.get('exit_time', '').strip()

        # Validación mínima
        error = None
        try:
            price = float(price_raw)
        except Exception:
            price = 0.0
        # Normalizar y validar el número de sala (acepta 'Sala 1', 'room-2', '1', etc.)
        room_number = normalize_room(room_raw) or 0

        if not buyer_name or not buyer_id:
            error = 'Nombre e ID son obligatorios.'
        elif price <= 0:
            error = 'Precio inválido.'
        elif room_number not in (1, 2):
            error = 'Número de sala inválido. Elija 1 o 2.'

        if error:
            flash(error)
            return redirect(url_for('karaoke'))

        # parse exit time if provided (expected format from datetime-local: YYYY-MM-DDTHH:MM)
        # If the hidden `exit_time` isn't present (e.g. JS failed), try a fallback
        # using the `exit_time_time` field (only HH:MM) combining with today's date.
        exit_time = None
        if not exit_raw:
            exit_time_time = request.form.get('exit_time_time', '').strip()
            if exit_time_time:
                today = datetime.now(timezone.utc)
                exit_raw = f"{today.year:04d}-{today.month:02d}-{today.day:02d}T{exit_time_time}"

        if exit_raw:
            try:
                # strip seconds if present
                if 'T' in exit_raw:
                    exit_time = datetime.strptime(exit_raw, '%Y-%m-%dT%H:%M')
                else:
                    exit_time = datetime.strptime(exit_raw, '%Y-%m-%d %H:%M')
            except Exception:
                exit_time = None

        # promo_type (select)
        promo_type = request.form.get('promo_type') or None

        # snacks_list: prefer JSON string in hidden field 'snacks_list'
        snacks_json = request.form.get('snacks_list') or None
        snacks_csv = None
        snacks_flag = False
        snacks_obj = None
        try:
            if snacks_json:
                snacks_obj = json.loads(snacks_json)
                # normalize to CSV of names for backward-compat
                names = [str(item.get('name')) for item in snacks_obj if item.get('name')]
                snacks_csv = ','.join(names) if names else None
                snacks_flag = True if names else False
        except Exception:
            snacks_json = None

        # Fallback: accept legacy 'snacks' form values (checkboxes or CSV)
        if not snacks_obj:
            raw_snacks = request.form.getlist('snacks') or []
            # if a single CSV string provided under 'snacks', split it
            if len(raw_snacks) == 1 and ',' in raw_snacks[0]:
                raw_snacks = [x.strip() for x in raw_snacks[0].split(',') if x.strip()]
            if raw_snacks:
                # build snack objects with qty=1 by default
                try:
                    # detect if values are numeric ids
                    items = []
                    for v in raw_snacks:
                        if v.isdigit():
                            items.append({'id': int(v), 'name': None, 'qty': 1, 'price': 0})
                        else:
                            items.append({'id': None, 'name': v, 'qty': 1, 'price': 0})
                    snacks_obj = items
                    snacks_json = json.dumps(snacks_obj)
                    snacks_csv = ','.join([it['name'] or '' for it in items if it.get('name')]) or snacks_csv
                    snacks_flag = True
                except Exception:
                    pass

        # mantener compatibilidad con los booleanos previos
        promo_flag = True if promo_type and promo_type.lower() != 'ninguna' else False

        # server-side: calcular total de snacks, validar stock y decrementar
        snack_total = 0.0
        snack_items = []
        if snacks_json:
            try:
                import json as _json
                snack_items = _json.loads(snacks_json)
            except Exception:
                snack_items = []

        # validate stock and compute total
        insufficient = None
        for it in snack_items:
            try:
                pid = int(it.get('id'))
            except Exception:
                pid = None
            qty = int(it.get('qty') or 0)
            if not pid or qty <= 0:
                continue
            prod = Product.query.get(pid)
            if not prod:
                continue
            if prod.stock < qty:
                insufficient = f"Stock insuficiente para {prod.name}: disponible {prod.stock}, pedido {qty}"
                break
            snack_total += float(prod.price) * qty

        if insufficient:
            flash(insufficient)
            return redirect(url_for('karaoke'))

        # decrementar stock ahora que todo está OK
        for it in snack_items:
            try:
                pid = int(it.get('id'))
            except Exception:
                pid = None
            qty = int(it.get('qty') or 0)
            if not pid or qty <= 0:
                continue
            prod = Product.query.get(pid)
            if not prod:
                continue
            prod.stock = max(0, prod.stock - qty)
            db.session.add(prod)

        # recalcular precio final: usar precio ingresado por el usuario (si válido) + snacks
        base_price = float(price) if float(price) > 0 else float(app.config.get('DEFAULT_TICKET_PRICE', 35.0))
        final_price = float(base_price) + float(snack_total)

        ticket = Ticket(
            buyer_name=buyer_name,
            buyer_id=buyer_id,
            buyer_phone=buyer_phone,
            price=final_price,
            room_number=room_number,
            exit_time=exit_time,
            entry_time=datetime.now(timezone.utc),
            promo=promo_flag,
            snacks=snacks_flag,
            promo_type=promo_type,
            snacks_list=snacks_json or snacks_csv,
            created_by=(session.get('user') or {}).get('username') if session.get('user') else None,
        )
        db.session.add(ticket)
        db.session.commit()
        try:
            notify_admins_of_payment({'reference': f'Ticket#{ticket.id}', 'amount': final_price, 'buyer': buyer_name, 'ticket_id': ticket.id})
        except Exception:
            app.logger.exception('notify_admins_of_payment failed after ticket creation')
        # Renderizar la factura inmediatamente para evitar problemas de redirección
        # Construir detalle de snacks igual que en la vista de factura
        snack_items_local = []
        snack_total_local = 0.0
        if ticket.snacks_list:
            try:
                possible = json.loads(ticket.snacks_list)
                if isinstance(possible, list):
                    for it in possible:
                        pid = None
                        name = None
                        qty = 1
                        price = 0.0
                        if isinstance(it, dict):
                            pid = int(it.get('id')) if it.get('id') else None
                            name = it.get('name')
                            try:
                                qty = int(it.get('qty') or 1)
                            except Exception:
                                qty = 1
                        else:
                            name = str(it)
                        if pid:
                            prod = Product.query.get(pid)
                            if prod:
                                price = float(prod.price)
                                name = prod.name
                        snack_total_local += price * qty
                        snack_items_local.append({'id': pid, 'name': name or '', 'qty': qty, 'price': price})
            except Exception:
                names = [x.strip() for x in (ticket.snacks_list or '').split(',') if x.strip()]
                for n in names:
                    snack_items_local.append({'id': None, 'name': n, 'qty': 1, 'price': 0.0})

        base_price_local = float(ticket.price) - float(snack_total_local)
        # Generar metadatos de factura (misma lógica que en la vista /invoice/<id>)
        try:
            if ticket_is_heladeria(ticket):
                local_kind = 'heladeria'
            elif getattr(ticket, 'room_number', 0) and int(getattr(ticket, 'room_number', 0)) > 0:
                local_kind = 'karaoke'
            else:
                local_kind = 'general'
        except Exception:
            local_kind = 'general'
        invoice_number = get_or_create_invoice_number(ticket.id, local_kind)
        issued_at = ticket.created_at
        tax_rate = float(app.config.get('TAX_RATE', 0.0) or 0.0)
        taxable_amount = base_price_local + float(snack_total_local)
        tax_amount = round(taxable_amount * tax_rate, 2)
        total_with_tax = round(taxable_amount + tax_amount, 2)

        return render_template('invoice.html', ticket=ticket, snack_items=snack_items_local, snack_total=snack_total_local, base_price=base_price_local, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_available=is_pdf_available())

    # GET: mostrar página con últimos boletos y productos disponibles
    # Asegurar columna buyer_phone en caso de BD SQLite antigua
    try:
        ensure_ticket_buyer_phone_column()
    except Exception:
        pass
    try:
        recent_tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(10).all()
    except OperationalError as oe:
        # intentar crear columna faltante y reintentar
        if 'no such column' in str(oe).lower() and 'snacks_total' in str(oe).lower():
            ensure_ticket_snacks_total_column()
            try:
                recent_tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(10).all()
            except Exception:
                recent_tickets = []
        else:
            recent_tickets = []
    products = Product.query.order_by(Product.name.asc()).all()
    default_price = float(app.config.get('DEFAULT_TICKET_PRICE', 35.0))
    return render_template('karaoke.html', user=session.get('user'), tickets=recent_tickets, products=products, default_price=default_price)


@app.route('/karaoke_demo')
def karaoke_demo():
    # Ruta temporal pública para ver la plantilla de karaoke sin iniciar sesión
    try:
        recent_tickets = Ticket.query.order_by(Ticket.created_at.desc()).limit(10).all()
        products = Product.query.order_by(Product.name.asc()).all()
    except Exception:
        recent_tickets = []
        products = []
    default_price = float(app.config.get('DEFAULT_TICKET_PRICE', 35.0))
    return render_template('karaoke.html', user={'username': 'demo', 'is_admin': False}, tickets=recent_tickets, products=products, default_price=default_price)


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = session.get('user')
        if not user or not user.get('is_admin'):
            flash('Acceso denegado: se requieren permisos de administrador.')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


# --- Administración: gestión de usuarios (lista y edición) ---------------------------------
@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    try:
        users = User.query.order_by(User.username.asc()).all()
    except Exception:
        users = []
    return render_template('users.html', users=users)


@app.route('/admin/users/<username>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_user_edit(username):
    u = User.query.filter_by(username=username).first()
    if not u:
        abort(404)
    if request.method == 'POST':
        try:
            email = request.form.get('email') or None
            role = request.form.get('role') or getattr(u, 'role', 'Staff')
            is_admin = True if request.form.get('is_admin') in ('1', 'on', 'true') else False
            password = request.form.get('password')
            must_change = request.form.get('must_change')
            u.email = email
            u.role = role
            u.is_admin = bool(is_admin)
            # manejar cambio de contraseña si se proporcionó
            if password:
                try:
                    u.password_hash = generate_password_hash(password)
                    # si viene el flag must_change, aplicarlo (checkbox viene en el form si está marcado)
                    if must_change is not None:
                        u.must_change_password = False if str(must_change).lower() in ('0', 'false', 'off', '') else True
                    else:
                        # si no viene el flag, no forzar por defecto
                        pass
                except Exception:
                    pass
            db.session.add(u)
            db.session.commit()
            flash('Usuario actualizado correctamente.')
            return redirect(url_for('admin_users'))
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            flash('Error actualizando el usuario.', 'danger')
            return redirect(url_for('admin_users'))
    # GET
    return render_template('admin_user_edit.html', user=u)


@app.route('/clientes')
@login_required
def clientes():
    """Lista clientes registrados (únicos por buyer_id) con conteo de boletos y última entrada."""
    try:
        from sqlalchemy import func, or_
        q = (request.args.get('q') or '').strip()
        qry = db.session.query(
            Ticket.buyer_id,
            Ticket.buyer_name,
            func.max(Ticket.buyer_phone).label('buyer_phone'),
            func.count(Ticket.id).label('tickets'),
            func.max(Ticket.created_at).label('last_visit')
        )
        if q:
            like = f"%{q}%"
            qry = qry.filter(or_(Ticket.buyer_name.ilike(like), Ticket.buyer_id.ilike(like)))
        rows = qry.group_by(Ticket.buyer_id, Ticket.buyer_name).order_by(func.count(Ticket.id).desc()).all()
        clients = [
            {'buyer_id': r[0], 'buyer_name': r[1], 'buyer_phone': r[2], 'tickets': int(r[3] or 0), 'last_visit': r[4]}
            for r in rows
        ]
    except Exception:
        app.logger.exception('Error listando clientes')
        clients = []
    return render_template('customers.html', clients=clients, user=session.get('user'), q=request.args.get('q',''))


@app.route('/clientes/<buyer_id>')
@login_required
def cliente_detail(buyer_id):
    """Detalle e historial de tickets para un cliente identificado por buyer_id."""
    try:
        tickets = Ticket.query.filter(Ticket.buyer_id == buyer_id).order_by(Ticket.created_at.desc()).all()
        buyer_name = tickets[0].buyer_name if tickets else ''
        buyer_phone = tickets[0].buyer_phone if tickets and getattr(tickets[0], 'buyer_phone', None) else ''
    except Exception:
        app.logger.exception('Error obteniendo historial del cliente %s', buyer_id)
        tickets = []
        buyer_name = ''
    return render_template('customer_detail.html', buyer_id=buyer_id, buyer_name=buyer_name, buyer_phone=buyer_phone, tickets=tickets, user=session.get('user'))


@app.route('/clientes/<buyer_id>/export.csv')
@login_required
def cliente_export_csv(buyer_id):
    """Exportar historial de tickets de un cliente como CSV."""
    try:
        tickets = Ticket.query.filter(Ticket.buyer_id == buyer_id).order_by(Ticket.created_at.desc()).all()
    except Exception:
        tickets = []

    def generate():
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['id', 'created_at', 'buyer_phone', 'room_number', 'price', 'created_by', 'promo', 'snacks'])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for t in tickets:
                writer.writerow([
                t.id,
                t.created_at.isoformat() if t.created_at else '',
                t.buyer_phone or '',
                t.room_number,
                ('%.2f' % t.price) if t.price is not None else '',
                t.created_by or '',
                'Sí' if t.promo else 'No',
                (t.snacks_list or '')
            ])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

    headers = {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="cliente_{buyer_id}_historial.csv"'
    }
    return Response(generate(), headers=headers)


# -- Payments (Yape) lightweight storage in data/payments.json
PAYMENTS_FILE = os.path.join(app.root_path, 'data', 'payments.json')

# Notifications file for admin alerts
NOTIFICATIONS_FILE = os.path.join(app.root_path, 'data', 'payment_notifications.json')

# Reservations storage (lightweight JSON)
RESERVATIONS_FILE = os.path.join(app.root_path, 'data', 'reservations.json')

def load_reservations():
    try:
        if os.path.exists(RESERVATIONS_FILE):
            with open(RESERVATIONS_FILE, 'r', encoding='utf-8') as fh:
                return json.load(fh) or []
    except Exception:
        app.logger.exception('Failed loading reservations')
    return []

def save_reservations(lst):
    try:
        os.makedirs(os.path.dirname(RESERVATIONS_FILE), exist_ok=True)
        tmp = RESERVATIONS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(lst, fh, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, RESERVATIONS_FILE)
        except Exception:
            try:
                os.remove(RESERVATIONS_FILE)
            except Exception:
                pass
            os.replace(tmp, RESERVATIONS_FILE)
        return True
    except Exception:
        app.logger.exception('Failed saving reservations')
        return False

def load_notifications():
    try:
        with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return []

def save_notifications(lst):
    try:
        os.makedirs(os.path.dirname(NOTIFICATIONS_FILE), exist_ok=True)
        with open(NOTIFICATIONS_FILE, 'w', encoding='utf-8') as fh:
            json.dump(lst, fh, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False

def notify_admins_of_payment(entry):
    """Create a persistent admin notification and attempt to email admins if they have emails configured."""
    try:
        note = {
            'reference': entry.get('reference'),
            'amount': entry.get('amount'),
            'buyer': entry.get('buyer'),
            'ticket_id': entry.get('ticket_id'),
            'created_at': datetime.utcnow().isoformat() + 'Z',
            'status': 'unread'
        }
        notes = load_notifications()
        notes.insert(0, note)
        save_notifications(notes)
    except Exception:
        app.logger.exception('Failed saving payment notification')

    # attempt to email admins
    try:
        admins = User.query.filter_by(is_admin=True).all()
        subject = f"Nuevo pago pendiente: {entry.get('reference')}"
        admin_link = url_for('admin_payments', _external=True) if 'admin_payments' in app.view_functions else url_for('admin', _external=True)
        body = f"Se registró un nuevo pago.\nReferencia: {entry.get('reference')}\nMonto: {entry.get('amount')}\nComprador: {entry.get('buyer')}\nTicket: {entry.get('ticket_id')}\nRevisar: {admin_link}\n"
        for a in admins:
            if a.email:
                try:
                    send_email(a.email, subject, body)
                except Exception:
                    app.logger.exception('Failed sending payment notification email to %s', a.email)
        # Emitir notificación en tiempo real a administradores conectados
        try:
            payload = {'type': 'payment', 'message': f"Pago pendiente: {entry.get('reference')} ({entry.get('amount')})", 'data': entry, 'for_admins': True}
            socketio.emit('notification', payload, room='admins')
        except Exception:
            app.logger.exception('Failed emitting socketio notification for payment')
    except Exception:
        app.logger.exception('Failed to notify admins of payment')

def load_payments():
    try:
        with open(PAYMENTS_FILE, 'r', encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return []

def save_payments(lst):
    try:
        os.makedirs(os.path.dirname(PAYMENTS_FILE), exist_ok=True)
        with open(PAYMENTS_FILE, 'w', encoding='utf-8') as fh:
            json.dump(lst, fh, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


@app.route('/api/payments/create', methods=['POST'])
@login_required
def api_payments_create():
    data = request.get_json() or {}
    try:
        amount = float(data.get('amount') or 0)
    except Exception:
        return jsonify({'error': 'invalid amount'}), 400
    if amount <= 0:
        return jsonify({'error': 'invalid amount'}), 400
    buyer = data.get('buyer') or ''
    ticket_id = data.get('ticket_id')
    reference = uuid4().hex[:12].upper()
    entry = {
        'reference': reference,
        'amount': round(amount, 2),
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat() + 'Z',
        'buyer': buyer,
        'ticket_id': ticket_id
    }
    payments = load_payments()
    payments.append(entry)
    save_payments(payments)
    # notify admins (persist notification + try email)
    try:
        notify_admins_of_payment(entry)
    except Exception:
        app.logger.exception('notify_admins_of_payment failed')
    phone = app.config.get('YAPE_PHONE', '+59163050841')
    payload = f"YAPE|REF:{reference}|PHONE:{phone}|AMOUNT:{entry['amount']:.2f} Bs"
    qr_url = 'https://chart.googleapis.com/chart?cht=qr&chs=300x300&chl=' + urllib.parse.quote(payload)
    return jsonify({'reference': reference, 'qr_url': qr_url, 'payload': payload})


@app.route('/api/tickets/create', methods=['POST'])
@login_required
def api_tickets_create():
    data = request.get_json() or {}
    buyer_name = (data.get('buyer_name') or '').strip()
    buyer_id = (data.get('buyer_id') or '').strip()
    buyer_phone = (data.get('buyer_phone') or '').strip()
    # Normalizar room_number si viene como 'Sala 1' u otros formatos
    try:
        room_number = normalize_room(data.get('room_number')) or 0
    except Exception:
        room_number = 0
    try:
        price = float(data.get('price') or app.config.get('DEFAULT_TICKET_PRICE', 35.0))
    except Exception:
        price = float(app.config.get('DEFAULT_TICKET_PRICE', 35.0))
    exit_time = None
    exit_raw = data.get('exit_time') or ''
    if exit_raw:
        try:
            if 'T' in exit_raw:
                exit_time = datetime.strptime(exit_raw, '%Y-%m-%dT%H:%M')
            else:
                exit_time = datetime.strptime(exit_raw, '%Y-%m-%d %H:%M')
        except Exception:
            exit_time = None

    snacks_list = data.get('snacks_list') or None
    snacks_flag = False
    snack_total = 0.0
    snack_items = []
    if snacks_list:
        try:
            snack_items = json.loads(snacks_list) if isinstance(snacks_list, str) else snacks_list
        except Exception:
            snack_items = []
    # validate and compute snack total
    for it in snack_items:
        try:
            pid = int(it.get('id')) if it.get('id') else None
        except Exception:
            pid = None
        qty = int(it.get('qty') or 0)
        if pid and qty > 0:
            prod = Product.query.get(pid)
            if prod and prod.stock >= qty:
                snack_total += float(prod.price) * qty
                prod.stock = max(0, prod.stock - qty)
                db.session.add(prod)
                snacks_flag = True

    # Use provided price from the API payload as base if valid, otherwise fallback to default
    base_price = float(price) if float(price) > 0 else float(app.config.get('DEFAULT_TICKET_PRICE', 35.0))
    final_price = float(base_price) + float(snack_total)

    # basic validation
    if not buyer_name or not buyer_id or room_number not in (1, 2):
        return jsonify({'error': 'invalid ticket data'}), 400

    ticket = Ticket(buyer_name=buyer_name, buyer_id=buyer_id, buyer_phone=buyer_phone, price=final_price, room_number=room_number, exit_time=exit_time, entry_time=datetime.now(timezone.utc), promo=False, snacks=snacks_flag, snacks_list=json.dumps(snack_items) if snack_items else None, snacks_total=snack_total)
    # registrar usuario creador si existe en sesión
    try:
        creator = (session.get('user') or {}).get('username') if session.get('user') else None
        ticket.created_by = creator
    except Exception:
        pass
    db.session.add(ticket)
    db.session.commit()
    create_audit(session.get('user', {}).get('username', 'unknown'), 'create_ticket_via_api', 'ticket', ticket.id, f'created by API for buyer {buyer_name}')
    # Emit a room-level event so karaoke clients can sync in real-time
    try:
        payload = {
            'action': 'ticket_created',
            'ticket': {
                'id': ticket.id,
                'buyer_name': ticket.buyer_name,
                'room': ticket.room_number,
                'price': ticket.price,
                'created_at': ticket.created_at.isoformat() if getattr(ticket, 'created_at', None) else None
            }
        }
        socketio.emit('karaoke_event', payload, room=f'room_{ticket.room_number}')
        # also notify admins
        try:
            socketio.emit('notification', {'message': f'Nuevo ticket en Sala {ticket.room_number}: {ticket.buyer_name}', 'type': 'info'}, room='admins')
        except Exception:
            app.logger.exception('Failed emitting admin notification for ticket_created')
    except Exception:
        app.logger.exception('Failed emitting socketio ticket_created event')

    return jsonify({'ticket_id': ticket.id, 'price': ticket.price})


@app.route('/api/payments/confirm', methods=['POST'])
def api_payments_confirm():
    """
    Confirmar pago: permite confirmación via admin session o vía webhook con secreto.
    Si se encuentra payment.ticket_id intenta marcar el `Ticket.paid = True` y devuelve la URL de la factura.
    """
    data = request.get_json() or {}
    # Autenticación: admin en sesión OR header X-PAYMENT-WEBHOOK-SECRET igual a config
    webhook_secret = app.config.get('PAYMENT_WEBHOOK_SECRET')
    header_secret = request.headers.get('X-PAYMENT-WEBHOOK-SECRET')
    is_admin = bool(session.get('user', {}).get('is_admin'))
    allowed = False
    if is_admin:
        allowed = True
    elif webhook_secret and header_secret and header_secret == webhook_secret:
        allowed = True

    if not allowed:
        return jsonify({'error': 'not authorized'}), 403

    ref = (data.get('reference') or '').strip()
    if not ref:
        return jsonify({'error': 'missing reference'}), 400

    payments = load_payments()
    found = False
    target = None
    for p in payments:
        if p.get('reference') == ref:
            p['status'] = 'paid'
            p['paid_at'] = datetime.utcnow().isoformat() + 'Z'
            found = True
            target = p
            break
    if not found:
        return jsonify({'error': 'reference not found'}), 404

    # persistir
    save_payments(payments)
    # Emitir notificación de pago confirmado a admins y persistir
    try:
        try:
            notify_admins_of_payment(target)
        except Exception:
            app.logger.exception('notify_admins_of_payment failed on confirm')
        try:
            payload = {'type': 'payment_confirmed', 'message': f"Pago confirmado: {ref}", 'data': target, 'for_admins': True}
            socketio.emit('notification', payload, room='admins')
        except Exception:
            app.logger.exception('Failed emitting socketio notification for payment confirm')
    except Exception:
        app.logger.exception('Unexpected error during payment confirm notification')

    invoice_url = None
    ticket_id = target.get('ticket_id')
    if ticket_id:
        try:
            t = Ticket.query.get(ticket_id)
            if t:
                # intentar marcar columna `paid`; si falta, añadirla con ALTER TABLE
                try:
                    setattr(t, 'paid', True)
                    db.session.add(t)
                    db.session.commit()
                except Exception:
                    try:
                        engine = getattr(db, 'engine', None) or db.get_engine(app)
                        with engine.connect() as conn:
                            conn.execute("ALTER TABLE ticket ADD COLUMN paid BOOLEAN DEFAULT 0")
                        # volver a establecer
                        t = Ticket.query.get(ticket_id)
                        setattr(t, 'paid', True)
                        db.session.add(t)
                        db.session.commit()
                    except Exception:
                        try:
                            db.session.rollback()
                        except Exception:
                            pass
                # generar URL de factura
                try:
                    invoice_url = url_for('invoice_ticket', ticket_id=t.id, _external=True)
                except Exception:
                    invoice_url = None
                # Emit room-level payment confirmation so karaoke clients can react
                try:
                    socketio.emit('karaoke_event', {'action': 'payment_confirmed', 'ticket_id': t.id, 'room': t.room_number, 'reference': ref}, room=f'room_{t.room_number}')
                except Exception:
                    app.logger.exception('Failed emitting payment_confirmed to room')
        except Exception:
            app.logger.exception('Error marcando ticket como pagado')

    resp = {'ok': True, 'reference': ref}
    if invoice_url:
        resp['invoice_url'] = invoice_url
    return jsonify(resp)


@app.route('/api/payments/status', methods=['POST'])
def api_payments_status():
    """Consultar estado de un pago por referencia. No requiere autenticación.
    Devuelve `status` y, si está pagado y tiene `ticket_id`, `invoice_url`.
    """
    data = request.get_json() or {}
    ref = (data.get('reference') or '').strip()
    if not ref:
        return jsonify({'error': 'missing reference'}), 400

    payments = load_payments()
    target = None
    for p in payments:
        if p.get('reference') == ref:
            target = p
            break
    if not target:
        return jsonify({'error': 'reference not found'}), 404

    resp = {'reference': ref, 'status': target.get('status', 'pending'), 'amount': target.get('amount')}
    ticket_id = target.get('ticket_id')
    if target.get('status') == 'paid' and ticket_id:
        try:
            t = Ticket.query.get(ticket_id)
            if t:
                try:
                    invoice_url = url_for('invoice_ticket', ticket_id=t.id, _external=True)
                    resp['invoice_url'] = invoice_url
                except Exception:
                    pass
        except Exception:
            app.logger.exception('Error fetching ticket for payment status')

    return jsonify(resp)


@app.route('/admin/notifications')
@login_required
@admin_required
def admin_notifications():
    notes = load_notifications()
    return render_template('admin_notifications.html', notifications=notes, user=session.get('user'))


@app.route('/admin/notifications/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_create_notification():
    if request.method == 'POST':
        data = request.form or {}
        title = (data.get('title') or '').strip()
        body = (data.get('body') or '').strip()
        amount = data.get('amount') or None
        for_all = True if data.get('for_all') in ('1', 'on', 'true', 'True') else False
        ref = uuid4().hex[:12].upper()
        note = {
            'reference': ref,
            'title': title or None,
            'body': body or None,
            'amount': float(amount) if amount else None,
            'for_all': bool(for_all),
            'status': 'unread',
            'created_at': datetime.utcnow().isoformat() + 'Z'
        }
        notes = load_notifications()
        notes.insert(0, note)
        save_notifications(notes)
        flash('Notificación creada.')
        return redirect(url_for('admin_notifications'))
    return render_template('admin_create_notification.html', user=session.get('user'))


@app.route('/admin/notifications/mark_read', methods=['POST'])
@login_required
@admin_required
def mark_notification_read():
    data = request.get_json() or {}
    ref = data.get('ref') or data.get('reference')
    if not ref:
        return jsonify({'success': False, 'error': 'missing reference'}), 400
    notes = load_notifications()
    changed = False
    for n in notes:
        # notifications store reference under 'reference'
        if n.get('reference') == ref or n.get('ref') == ref:
            n['status'] = 'read'
            n['read_at'] = datetime.utcnow().isoformat() + 'Z'
            changed = True
            break
    if changed:
        save_notifications(notes)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'not found'}), 404


@app.route('/notifications')
@login_required
def notifications():
    # show public/general notifications to any logged user
    notes = load_notifications()
    public = [n for n in notes if n.get('for_all')]
    return render_template('notifications.html', notifications=public, user=session.get('user'))


@app.route('/notifications/mark_read', methods=['POST'])
@login_required
def mark_public_notification_read():
    data = request.get_json() or {}
    ref = data.get('ref') or data.get('reference')
    if not ref:
        return jsonify({'success': False, 'error': 'missing reference'}), 400
    notes = load_notifications()
    changed = False
    for n in notes:
        if (n.get('reference') == ref or n.get('ref') == ref) and n.get('for_all'):
            n['status'] = 'read'
            n['read_at'] = datetime.utcnow().isoformat() + 'Z'
            changed = True
            break
    if changed:
        save_notifications(notes)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'not found or not public'}), 404


def no_personal_nuevo(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = session.get('user')
        if not user:
            return redirect(url_for('login'))
        if user.get('role') == 'Personal Nuevo':
            flash('Acceso restringido para este rol.')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated


@app.route('/admin')
@login_required
@admin_required
def admin():
    # Calcular métricas para el panel de administración
    try:
        total_users = User.query.count()
    except Exception:
        total_users = None

    # Ingresos del mes en Bolivianos y desglose por día y por sala
    try:
        from sqlalchemy import func
        now = datetime.now(timezone.utc)
        # determinar salas permitidas (p. ej. karaoke salas)
        cfg = read_settings() or {}
        allowed_env = cfg.get('ROOMS') or os.environ.get('ROOMS')
        if allowed_env is None:
            allowed = {1, 2}
        else:
            try:
                allowed = set(int(x.strip()) for x in allowed_env.split(',') if x.strip())
            except Exception:
                allowed = {1, 2}

        # Empezar todo desde el inicio del día de hoy (UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        # Sumar solo tickets de las salas permitidas desde hoy (incluye snacks en Ticket.price)
        monthly_sum = db.session.query(func.coalesce(func.sum(Ticket.price), 0.0)).filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).scalar()
        monthly_income_bs = float(monthly_sum or 0.0)

        # Desglose por día (usar formato YYYY-MM-DD) — solo desde hoy
        daily_q = db.session.query(func.strftime('%Y-%m-%d', Ticket.created_at).label('day'), func.coalesce(func.sum(Ticket.price), 0.0))
        daily_q = daily_q.filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).group_by('day').order_by('day').all()
        daily_breakdown = [{'date': r[0], 'income': float(r[1] or 0.0)} for r in daily_q]

        # Desglose por sala: número de tickets y suma de ingresos por sala — solo desde hoy
        room_q = db.session.query(Ticket.room_number.label('room'), func.count(Ticket.id).label('tickets'), func.coalesce(func.sum(Ticket.price), 0.0).label('income'))
        room_q = room_q.filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).group_by('room').order_by('room').all()
        room_breakdown = [{'room': int(r[0]), 'tickets': int(r[1]), 'income': float(r[2] or 0.0)} for r in room_q]
        # room_breakdown ya contiene sólo salas permitidas
        # Totales filtrados (puede usarse en plantilla si se desea)
        total_tickets_rooms = sum(r['tickets'] for r in room_breakdown)
        total_revenue_rooms = sum(r['income'] for r in room_breakdown)
        # Sumar ventas de snacks por separado (si la columna existe)
        try:
            snacks_sum = db.session.query(func.coalesce(func.sum(Ticket.snacks_total), 0.0)).filter(Ticket.created_at >= today_start).filter(Ticket.room_number.in_(list(allowed))).scalar()
            snacks_sum = float(snacks_sum or 0.0)
        except Exception:
            snacks_sum = 0.0
    except Exception:
        monthly_income_bs = None
        daily_breakdown = []
        room_breakdown = []

    # obtener actividad reciente
    # obtener actividad reciente — sólo desde hoy
    try:
        now = datetime.now(timezone.utc)
        today_start_recent = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        recent_tickets = Ticket.query.filter(Ticket.created_at >= today_start_recent).order_by(Ticket.created_at.desc()).limit(5).all()
    except Exception:
        recent_tickets = []
    try:
        recent_users = User.query.filter(User.created_at >= today_start_recent).order_by(User.created_at.desc()).limit(5).all()
    except Exception:
        recent_users = []

    # Render con métricas calculadas para el MES actual (incluye snacks)
    try:
        from sqlalchemy import func
        now = datetime.now(timezone.utc)
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

        # ingresos mes (tickets.price ya incluye snacks_total si implementado así)
        monthly_sum = db.session.query(func.coalesce(func.sum(Ticket.price), 0.0)).filter(Ticket.created_at >= month_start).filter(Ticket.room_number.in_(list(allowed))).scalar()
        monthly_income_bs = float(monthly_sum or 0.0)

        # desglose diario del mes
        daily_q = db.session.query(func.strftime('%Y-%m-%d', Ticket.created_at).label('day'), func.coalesce(func.sum(Ticket.price), 0.0))
        daily_q = daily_q.filter(Ticket.created_at >= month_start).filter(Ticket.room_number.in_(list(allowed))).group_by('day').order_by('day').all()
        daily_breakdown = [{'date': r[0], 'income': float(r[1] or 0.0)} for r in daily_q]

        # desglose por sala para el mes
        room_q = db.session.query(Ticket.room_number.label('room'), func.count(Ticket.id).label('tickets'), func.coalesce(func.sum(Ticket.price), 0.0).label('income'))
        room_q = room_q.filter(Ticket.created_at >= month_start).filter(Ticket.room_number.in_(list(allowed))).group_by('room').order_by('room').all()
        room_breakdown = [{'room': int(r[0]), 'tickets': int(r[1]), 'income': float(r[2] or 0.0)} for r in room_q]
        total_tickets_rooms = sum(r['tickets'] for r in room_breakdown)
        total_revenue_rooms = sum(r['income'] for r in room_breakdown)

        # snacks por mes (si existe la columna snacks_total)
        try:
            snacks_sum = db.session.query(func.coalesce(func.sum(Ticket.snacks_total), 0.0)).filter(Ticket.created_at >= month_start).filter(Ticket.room_number.in_(list(allowed))).scalar()
            snacks_sum = float(snacks_sum or 0.0)
        except Exception:
            snacks_sum = locals().get('snacks_sum', 0.0)
    except Exception:
        # fallback si algo falla
        monthly_income_bs = monthly_income_bs if 'monthly_income_bs' in locals() else None
        daily_breakdown = daily_breakdown if 'daily_breakdown' in locals() else []
        room_breakdown = room_breakdown if 'room_breakdown' in locals() else []
        total_tickets_rooms = total_tickets_rooms if 'total_tickets_rooms' in locals() else 0
        total_revenue_rooms = total_revenue_rooms if 'total_revenue_rooms' in locals() else 0.0

    # obtener actividad reciente — últimos 10 tickets (globales)
    try:
        recent_tickets = db.session.query(Ticket).order_by(Ticket.created_at.desc()).limit(10).all()
    except Exception:
        recent_tickets = []

    return render_template('admin_dashboard.html', title='Admin', heading='Panel de administración', total_users=total_users, monthly_income_bs=monthly_income_bs, daily_breakdown=daily_breakdown, room_breakdown=room_breakdown, total_tickets_rooms=total_tickets_rooms, total_revenue_rooms=total_revenue_rooms, snacks_sum=locals().get('snacks_sum', 0.0), recent_tickets=recent_tickets, recent_users=recent_users)


@app.route('/admin/payments')
@login_required
@admin_required
def admin_payments():
    payments = load_payments()
    def _parse_created_at(entry):
        ca = entry.get('created_at')
        if not ca:
            return None
        try:
            if ca.endswith('Z'):
                ca = ca[:-1]
            return datetime.fromisoformat(ca)
        except Exception:
            return None

    today_utc = datetime.utcnow().date()
    filtered = []
    for p in payments:
        dt = _parse_created_at(p)
        if dt and dt.date() >= today_utc:
            filtered.append(p)
    try:
        payments = sorted(filtered, key=lambda x: x.get('created_at') or '', reverse=True)
    except Exception:
        payments = filtered
    return render_template('admin_payments.html', payments=payments)





@app.route('/admin/rooms', methods=['GET'])
@login_required
@admin_required
def admin_rooms():
    # Parámetros opcionales: start, end (YYYY-MM-DD)
    start = request.args.get('start')
    end = request.args.get('end')
    export = request.args.get('export')  # 'csv' or 'pdf' or None
    from sqlalchemy import func
    q = db.session.query(Ticket.room_number.label('room'), func.count(Ticket.id).label('tickets'), func.coalesce(func.sum(Ticket.price), 0.0).label('income'))
    try:
        if start:
            try:
                start_dt = datetime.fromisoformat(start)
            except Exception:
                start_dt = datetime.fromisoformat(start + 'T00:00:00')
            q = q.filter(Ticket.created_at >= start_dt)
        if end:
            try:
                end_dt = datetime.fromisoformat(end)
            except Exception:
                end_dt = datetime.fromisoformat(end + 'T23:59:59')
            q = q.filter(Ticket.created_at <= end_dt)
    except Exception:
        # ignore parse errors and show unfiltered
        start = None
        end = None

    q = q.group_by('room').order_by('room')
    rows = q.all()
    per_room = [{'room': int(r[0]), 'tickets': int(r[1]), 'income': float(r[2] or 0.0)} for r in rows]
    # Filtrar por salas reales: preferir instance/settings.json 'ROOMS', si no usar variable de entorno; por defecto {1,2}.
    cfg = read_settings() or {}
    allowed_env = cfg.get('ROOMS') or os.environ.get('ROOMS')
    if allowed_env is None:
        allowed = {1, 2}
    else:
        try:
            allowed = set(int(x.strip()) for x in allowed_env.split(',') if x.strip())
        except Exception:
            allowed = {1, 2}
    per_room = [r for r in per_room if r['room'] in allowed]
    total_tickets = sum(r['tickets'] for r in per_room)
    total_revenue = sum(r['income'] for r in per_room)

    # Export CSV
    if export == 'csv':
        import io, csv
        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow(['room', 'tickets', 'revenue_bob'])
        for r in per_room:
            writer.writerow([r['room'], r['tickets'], r['income']])
        mem = si.getvalue().encode('utf-8')
        resp = make_response(mem)
        resp.headers['Content-Type'] = 'text/csv; charset=utf-8'
        resp.headers['Content-Disposition'] = 'attachment; filename="room_breakdown.csv"'
        return resp

    # Export PDF
    if export == 'pdf':
        # render HTML and try to convert with pdfkit if available
        html = render_template('admin_rooms.html', per_room=per_room, total_tickets=total_tickets, total_revenue=total_revenue, start=start, end=end)
        try:
            import pdfkit
            wk = detect_wkhtmltopdf()
            config = pdfkit.configuration(wkhtmltopdf=wk) if wk else None
            pdf = pdfkit.from_string(html, False, configuration=config)
            resp = make_response(pdf)
            resp.headers['Content-Type'] = 'application/pdf'
            resp.headers['Content-Disposition'] = 'attachment; filename="room_breakdown.pdf"'
            return resp
        except Exception:
            flash('No está disponible la generación de PDF (faltan dependencias o wkhtmltopdf). Se muestra HTML.')

    return render_template('admin_rooms.html', per_room=per_room, total_tickets=total_tickets, total_revenue=total_revenue, start=start, end=end)


@app.route('/admin/reports/room_breakdown.csv', methods=['GET'])
@login_required
@admin_required
def download_room_breakdown():
    # Generar CSV dinámico desde la BD (tickets agrupados por sala)
    from sqlalchemy import func
    cfg = read_settings() or {}
    allowed_env = cfg.get('ROOMS') or os.environ.get('ROOMS')
    if allowed_env is None:
        allowed = [1, 2]
    else:
        try:
            allowed = [int(x.strip()) for x in allowed_env.split(',') if x.strip()]
        except Exception:
            allowed = [1, 2]

    try:
        rows = db.session.query(Ticket.room_number.label('room'), func.count(Ticket.id).label('tickets'), func.coalesce(func.sum(Ticket.price), 0.0).label('revenue')).filter(Ticket.room_number.in_(allowed)).group_by('room').order_by('room').all()
    except Exception:
        rows = []

    import io as _io, csv as _csv
    buf = _io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(['room', 'tickets', 'revenue_bob'])
    total_tickets = 0
    total_revenue = 0.0
    # write rows for allowed rooms (ensure we include rooms even if count==0)
    rooms_seen = {int(r[0]) for r in rows if r and r[0] is not None}
    for rnum in allowed:
        if rnum in rooms_seen:
            for rr in rows:
                if int(rr[0]) == int(rnum):
                    tickets = int(rr[1] or 0)
                    revenue = float(rr[2] or 0.0)
                    writer.writerow([rnum, tickets, f"{revenue:.2f}"])
                    total_tickets += tickets
                    total_revenue += revenue
                    break
        else:
            writer.writerow([rnum, 0, f"{0.00:.2f}"])

    writer.writerow(['Total', total_tickets, f"{total_revenue:.2f}"])
    resp = Response(buf.getvalue(), mimetype='text/csv')
    resp.headers['Content-Disposition'] = 'attachment; filename="room_breakdown.csv"'
    return resp


@app.route('/admin/audit', methods=['GET'])
@login_required
@admin_required
def admin_audit():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(500).all()
    return render_template('audit_log.html', logs=logs)


@app.route('/admin/user/<int:user_id>/edit', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def user_edit(user_id):
    u = User.query.get_or_404(user_id)
    # soportar edición de email, role, admin flag y cambio de contraseña
    new_email = request.form.get('email')
    new_role = request.form.get('role')
    set_admin = request.form.get('is_admin')
    new_password = request.form.get('password')
    force_change = request.form.get('must_change')
    try:
        changed = False
        if new_email is not None:
            u.email = new_email.strip() or None
            changed = True
        if new_role:
            u.role = new_role.strip()
            changed = True
        # Manejar checkbox: si viene en el form, interpretamos su valor; si no viene, lo consideramos desmarcado
        prev_admin = bool(u.is_admin)
        # Valor aceptable para 'true' cuando proviene del checkbox
        if 'is_admin' in request.form:
            v = request.form.get('is_admin')
            new_admin = False if str(v).lower() in ('0', 'false', 'off', '') else True
        else:
            new_admin = False
        if new_admin != prev_admin:
            u.is_admin = new_admin
            changed = True
        if new_password:
            u.password_hash = generate_password_hash(new_password)
            # si el admin establece la contraseña, respetar la casilla 'must_change' si viene
            if 'must_change' in request.form:
                v = request.form.get('must_change')
                u.must_change_password = False if str(v).lower() in ('0', 'false', 'off', '') else True
            changed = True
        else:
            # Si no se cambia la contraseña, igual podemos actualizar el flag must_change según el checkbox
            if 'must_change' in request.form:
                v = request.form.get('must_change')
                new_flag = False if str(v).lower() in ('0', 'false', 'off', '') else True
                if bool(u.must_change_password) != new_flag:
                    u.must_change_password = new_flag
                    changed = True
        if changed:
            db.session.commit()
            # Si el usuario editado es el que está en sesión, actualizar la sesión
            try:
                current_username = session.get('user', {}).get('username')
                if current_username and current_username == u.username:
                    session_user = session.get('user', {})
                    session_user['is_admin'] = bool(u.is_admin)
                    session_user['role'] = u.role or session_user.get('role')
                    session['user'] = session_user
            except Exception:
                # no fatal: continuar
                pass
            msg = 'Usuario actualizado.'
            flash(msg)
            try:
                create_audit(session.get('user', {}).get('username'), 'edit_user', 'user', u.id, details=f'edited user {u.username}')
            except Exception:
                pass
        else:
            msg = 'No se detectaron cambios.'
            flash(msg)
    except Exception as e:
        db.session.rollback()
        flash('Error al actualizar usuario: ' + str(e))
        msg = 'error'
    # If request from AJAX, return JSON with updated fields
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.accept_mimetypes.accept_json:
        try:
            return jsonify({
                'status': 'ok' if msg != 'error' else 'error',
                'message': msg,
                'user': {
                    'id': u.id,
                    'username': u.username,
                    'email': u.email,
                    'role': u.role,
                    'is_admin': bool(u.is_admin),
                    'must_change_password': bool(u.must_change_password),
                    'created_at': u.created_at.isoformat() if u.created_at else None,
                    'created_by': u.created_by
                }
            })
        except Exception:
            return jsonify({'status': 'error', 'message': 'Error generando respuesta JSON'})
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/json', methods=['GET'])
@login_required
@admin_required
def user_info(user_id):
    u = User.query.get_or_404(user_id)
    try:
        return jsonify({
            'status': 'ok',
            'user': {
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'role': u.role,
                'is_admin': bool(u.is_admin),
                'must_change': bool(u.must_change_password)
            }
        })
    except Exception:
        return jsonify({'status': 'error', 'message': 'Error generando respuesta JSON'})


@app.route('/admin/user/<int:user_id>/reset', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def user_reset(user_id):
    u = User.query.get_or_404(user_id)
    # generar nueva contraseña temporal
    import secrets, string
    alphabet = string.ascii_letters + string.digits
    newpw = ''.join(secrets.choice(alphabet) for _ in range(10))
    try:
        u.password_hash = generate_password_hash(newpw)
        u.must_change_password = True
        db.session.commit()
        msg = f'Contraseña reseteada. Nueva contraseña: {newpw}'
        flash(msg)
        # intentar enviar por correo si existe configuración y usuario proporcionó email (no guardamos email ahora)
    except Exception as e:
        db.session.rollback()
        msg = 'error'
        flash('Error al resetear contraseña: ' + str(e))
    # If AJAX request, return JSON including new password (admin only)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.accept_mimetypes.accept_json:
        try:
            try:
                create_audit(session.get('user', {}).get('username'), 'reset_password', 'user', u.id, details='password reset by admin')
            except Exception:
                pass
            return jsonify({'status': 'ok' if msg != 'error' else 'error', 'message': msg, 'new_password': newpw if msg != 'error' else None, 'user_id': u.id})
        except Exception:
            return jsonify({'status': 'error', 'message': 'Error generando respuesta JSON'})
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def user_delete(user_id):
    u = User.query.get_or_404(user_id)
    try:
        current = session.get('user', {}).get('username')
        if current and current == u.username:
            msg = 'No puedes eliminar la cuenta con la que iniciaste sesión.'
            flash(msg)
        else:
            db.session.delete(u)
            db.session.commit()
            msg = 'Usuario eliminado.'
            flash(msg)
            try:
                create_audit(session.get('user', {}).get('username'), 'delete_user', 'user', user_id, details=f'deleted user {u.username}')
            except Exception:
                pass
    except Exception as e:
        db.session.rollback()
        msg = 'error'
        flash('Error al eliminar usuario: ' + str(e))
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json or request.accept_mimetypes.accept_json:
        try:
            return jsonify({'status': 'ok' if msg != 'error' else 'error', 'message': msg, 'user_id': user_id if msg != 'error' else None})
        except Exception:
            return jsonify({'status': 'error', 'message': 'Error generando respuesta JSON'})
    return redirect(url_for('admin_users'))


@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_settings():
    message = None
    if request.method == 'POST':
        wk = request.form.get('wkhtmltopdf_path') or ''
        cfg = read_settings()
        cfg['wkhtmltopdf_path'] = wk.strip()
        ok = write_settings(cfg)
        if ok:
            flash('Configuración guardada.')
        else:
            flash('Error al guardar la configuración.')
        return redirect(url_for('admin_settings'))

    cfg = read_settings()
    wk_path = cfg.get('wkhtmltopdf_path') if isinstance(cfg, dict) else None
    return render_template('admin_settings.html', wk_path=wk_path)


@app.route('/_force_admin_login')
def _force_admin_login():
    # Ruta de desarrollo para facilitar pruebas locales: crea sesión admin demo
    session['user'] = {'username': os.environ.get('ADMIN_USERNAME', 'admin'), 'is_admin': True}
    flash('Sesión de administrador (demo) iniciada.')
    return redirect(url_for('inventory'))


@app.route('/inventory', methods=['GET', 'POST'])
def inventory():
    # Allow GET for everyone (view only). Restrict POST actions to admins.
    if request.method == 'POST':
        user = session.get('user')
        if not user or not user.get('is_admin'):
            flash('Acceso denegado: se requieren permisos de administrador.')
            return redirect(url_for('inventory'))

        # Add product
        if request.form.get('action') == 'add':
            name = request.form.get('name', '').strip()
            try:
                price = float(request.form.get('price', '0') or 0)
            except Exception:
                price = 0.0
            try:
                stock = int(request.form.get('stock', '0') or 0)
            except Exception:
                stock = 0
            if name:
                p = Product(name=name, price=price, stock=stock)
                db.session.add(p)
                db.session.commit()
                flash('Producto agregado.')
            return redirect(url_for('inventory'))

        # Edit existing product
        if request.form.get('edit_id'):
            try:
                pid = int(request.form.get('edit_id'))
                p = Product.query.get(pid)
                if p:
                    new_name = request.form.get('edit_name', p.name).strip()
                    try:
                        new_price = float(request.form.get('edit_price', p.price))
                    except Exception:
                        new_price = p.price
                    try:
                        new_stock = int(request.form.get('edit_stock', p.stock))
                    except Exception:
                        new_stock = p.stock
                    p.name = new_name
                    p.price = new_price
                    p.stock = new_stock
                    db.session.add(p)
                    db.session.commit()
                    flash('Producto actualizado.')
            except Exception:
                pass
            return redirect(url_for('inventory'))

        # Delete product
        if request.form.get('delete_id'):
            try:
                pid = int(request.form.get('delete_id'))
                p = Product.query.get(pid)
                if p:
                    db.session.delete(p)
                    db.session.commit()
                    flash('Producto eliminado.')
            except Exception:
                pass
            return redirect(url_for('inventory'))

    products = Product.query.order_by(Product.name.asc()).all()
    return render_template('inventory.html', products=products, user=session.get('user'))


@app.route('/staff/new', methods=['GET', 'POST'])
@login_required
@admin_required
@csrf_protect
def staff_new():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        role = (request.form.get('role') or 'Staff').strip()
        email_addr = (request.form.get('email') or '').strip()
        given_password = (request.form.get('password') or '').strip()
        if not name:
            flash('Nombre requerido.')
            return redirect(url_for('staff_new'))

        # generar username friendly
        base = ''.join(ch for ch in name.lower() if ch.isalnum() or ch == '_' or ch == '-')
        if not base:
            base = 'user'
        username = base
        # asegurar unicidad (manejar excepción si la columna is_admin falta)
        suffix = 1
        while True:
            try:
                exists = User.query.filter_by(username=username).first()
            except OperationalError as oe:
                msg = str(oe).lower()
                if 'no such column' in msg and 'is_admin' in msg:
                    try:
                        engine = getattr(db, 'engine', None) or db.get_engine(app)
                        with engine.connect() as conn:
                            conn.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                    except Exception:
                        pass
                    # retry the query after attempting to add the column
                    try:
                        exists = User.query.filter_by(username=username).first()
                    except Exception:
                        exists = None
                else:
                    raise

            if not exists:
                break
            username = f"{base}{suffix}"
            suffix += 1

        # generar contraseña si no se proporcionó
        alphabet = string.ascii_letters + string.digits
        if given_password:
            password = given_password
        else:
            password = ''.join(secrets.choice(alphabet) for _ in range(10))

        try:
            is_admin_flag = True if role.lower() == 'admin' else False
            # si la contraseña fue generada automáticamente, forzar cambio en primer login
            must_change = False if given_password else True
            user = User.create(username, password, email=email_addr or None, role=role, is_admin=is_admin_flag, must_change_password=must_change, created_by=session.get('user', {}).get('username'), created_at=datetime.now(timezone.utc))
            db.session.add(user)
            db.session.commit()
            flash(f'Personal "{name}" agregado. Usuario: {username} — Contraseña: {password}')

            # intentar enviar credenciales por correo si se proporcionó email y SMTP está configurado
            if email_addr:
                try:
                    subj = 'Credenciales de acceso - Seoul Voice'
                    body = (
                        f"Hola {name},\n\nSe ha creado una cuenta para ti en Seoul Voice.\n"
                        f"Usuario: {username}\nContraseña temporal: {password}\n\nCambia la contraseña al iniciar sesión.\n"
                    )
                    send_email(email_addr, subj, body)
                    flash('Se intentó enviar las credenciales por correo.')
                except Exception:
                    app.logger.exception('Error enviando correo de credenciales')
            # Audit: creación de personal
            try:
                create_audit(session.get('user', {}).get('username'), 'create_user', 'user', username, details=f'Created user {username} role={role} admin={is_admin_flag}')
            except Exception:
                pass
        except Exception as e:
            db.session.rollback()
            flash('Error al crear el usuario: ' + str(e))
        return redirect(url_for('admin'))

    return render_template('simple_page.html', title='Agregar personal', heading='Agregar personal', show_form=True)


@app.route('/productos')
def productos():
    # Preferir carga desde data/products.json si existe, sino intentar leer desde la BD
    products_path = os.path.join(app.root_path, 'data', 'products.json')
    items = []
    try:
        if os.path.exists(products_path):
            with open(products_path, 'r', encoding='utf-8') as fh:
                items = json.load(fh) or []
            # Normalizar y asegurar campos mínimos
            for idx, it in enumerate(items, start=1):
                if isinstance(it, dict):
                    # id
                    if 'id' not in it:
                        it['id'] = idx
                    try:
                        it['id'] = int(it['id'])
                    except Exception:
                        it['id'] = idx
                    # price_bs
                    try:
                        it['price_bs'] = float(it.get('price_bs') or it.get('price') or 0.0)
                    except Exception:
                        it['price_bs'] = 0.0
                    # stock
                    try:
                        it['stock'] = int(it.get('stock') or 0)
                    except Exception:
                        it['stock'] = 0
                    # image
                    if not it.get('image'):
                        it['image'] = '/static/img/placeholder.svg'
                    # sku
                    if not it.get('sku'):
                        try:
                            it['sku'] = f"SV-{int(it['id']):04d}"
                        except Exception:
                            it['sku'] = f"SV-{idx:04d}"
                else:
                    # if item is a plain string, wrap into a dict for compatibility
                    items[idx-1] = {'id': idx, 'name': str(it), 'price_bs': 0.0, 'stock': 0, 'image': '/static/img/placeholder.svg', 'sku': f"SV-{idx:04d}"}
        else:
            # Fallback: leer desde la tabla Product si está disponible
            try:
                prods = Product.query.order_by(Product.name.asc()).all()
                for p in prods:
                    items.append({'id': p.id, 'name': p.name, 'price_bs': float(p.price or 0.0), 'stock': int(p.stock or 0), 'image': '/static/img/placeholder.svg', 'sku': f"SV-{int(p.id):04d}"})
            except Exception:
                items = []
    except Exception:
        items = []
    return render_template('simple_page.html', title='Productos', heading='Productos', items=items)


@app.route('/ramos')
def ramos():
    """Página específica para venta de ramos de rosas (filtra productos que contienen 'rosa')."""
    products_path = os.path.join(app.root_path, 'data', 'products.json')
    items = []
    try:
        if os.path.exists(products_path):
            with open(products_path, 'r', encoding='utf-8') as fh:
                allp = json.load(fh) or []
            # filtrar por nombre que contenga 'rosa' (case-insensitive)
            for it in allp:
                try:
                    name = (it.get('name') or '') if isinstance(it, dict) else str(it)
                    if 'rosa' in name.lower():
                        # ensure normalized fields (id, sku, price_bs, stock, image, description)
                        if not isinstance(it, dict):
                            continue
                        it['id'] = int(it.get('id') or 0)
                        it['sku'] = it.get('sku') or f"SV-{int(it.get('id') or 0):04d}"
                        it['price_bs'] = float(it.get('price_bs') or it.get('price') or 0.0)
                        it['stock'] = int(it.get('stock') or 0)
                        it['image'] = it.get('image') or '/static/img/placeholder.svg'
                        items.append(it)
                except Exception:
                    continue
    except Exception:
        items = []
    return render_template('ramos.html', title='Ramos', heading='Ramos de rosas', items=items)


@app.route('/ramos/purchase', methods=['POST'])
def ramos_purchase():
    data = request.get_json() or {}
    pid = str(data.get('id') or '')
    try:
        qty = int(data.get('qty') or 1)
    except Exception:
        qty = 1

    if not pid:
        return jsonify(ok=False, message='Producto no especificado')

    products = load_products()
    for p in products:
        try:
            if str(int(p.get('id') or 0)) == str(int(pid)):
                stock = int(p.get('stock') or 0)
                if qty < 1:
                    return jsonify(ok=False, message='Cantidad inválida')
                if stock < qty:
                    return jsonify(ok=False, message='Stock insuficiente', current_stock=stock)
                p['stock'] = stock - qty
                save_products(products)
                return jsonify(ok=True, message='Compra exitosa', new_stock=p['stock'])
        except Exception:
            continue

    return jsonify(ok=False, message='Producto no encontrado')


@app.route('/productos/create', methods=['POST'])
def create_product():
    products_path = os.path.join(app.root_path, 'data', 'products.json')
    os.makedirs(os.path.dirname(products_path), exist_ok=True)
    name = request.form.get('name', '').strip()
    sku = request.form.get('sku', '').strip() or None
    try:
        price_bs = float(request.form.get('price_bs') or 0.0)
    except Exception:
        price_bs = 0.0
    try:
        stock = int(request.form.get('stock') or 0)
    except Exception:
        stock = 0
    description = request.form.get('description') or ''

    # manejar imagen
    image_url = '/static/img/placeholder.svg'
    f = request.files.get('image')
    if f and getattr(f, 'filename', None):
        filename = secure_filename(f.filename)
        uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        save_name = f"{int(time.time())}_{filename}"
        save_path = os.path.join(uploads_dir, save_name)
        try:
            f.save(save_path)
            image_url = f"/static/uploads/{save_name}"
        except Exception:
            image_url = '/static/img/placeholder.svg'

    # cargar existentes y agregar
    try:
        with open(products_path, 'r', encoding='utf-8') as fh:
            items = json.load(fh) or []
    except Exception:
        items = []

    new_id = 1
    try:
        ids = [int(it.get('id') or 0) for it in items if isinstance(it, dict) and it.get('id')]
        if ids:
            new_id = max(ids) + 1
    except Exception:
        new_id = len(items) + 1

    prod = {'id': new_id, 'name': name or f'Producto {new_id}', 'sku': sku or f"SV-{new_id:04d}", 'price_bs': price_bs, 'stock': stock, 'image': image_url, 'description': description}
    items.append(prod)
    try:
        with open(products_path, 'w', encoding='utf-8') as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
        flash('Producto creado correctamente.')
    except Exception as e:
        app.logger.exception('Error saving products.json: %s', e)
        flash('Error creando producto.')

    return redirect(url_for('productos'))


@app.route('/productos/<int:prod_id>/edit', methods=['POST'])
def edit_product(prod_id):
    products_path = os.path.join(app.root_path, 'data', 'products.json')
    if not os.path.exists(products_path):
        return jsonify({'ok': False, 'error': 'products.json no encontrado'}), 404

    # Accept JSON or form-data
    data = {}
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()

    # handle image upload
    f = request.files.get('image')
    image_url = None
    if f and getattr(f, 'filename', None):
        filename = secure_filename(f.filename)
        uploads_dir = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(uploads_dir, exist_ok=True)
        save_name = f"{int(time.time())}_{filename}"
        save_path = os.path.join(uploads_dir, save_name)
        try:
            f.save(save_path)
            image_url = f"/static/uploads/{save_name}"
        except Exception:
            image_url = None

    try:
        with open(products_path, 'r', encoding='utf-8') as fh:
            items = json.load(fh) or []
    except Exception:
        return jsonify({'ok': False, 'error': 'Error leyendo products.json'}), 500

    updated = None
    for it in items:
        try:
            if int(it.get('id')) == int(prod_id):
                # actualizar campos si vienen
                if 'name' in data:
                    it['name'] = data.get('name')
                if 'sku' in data:
                    it['sku'] = data.get('sku')
                if 'price_bs' in data:
                    try:
                        it['price_bs'] = float(data.get('price_bs') or it.get('price_bs') or 0.0)
                    except Exception:
                        pass
                if 'stock' in data:
                    try:
                        it['stock'] = int(data.get('stock') or it.get('stock') or 0)
                    except Exception:
                        pass
                if 'description' in data:
                    it['description'] = data.get('description')
                if image_url:
                    it['image'] = image_url
                updated = it
                break
        except Exception:
            continue

    if not updated:
        return jsonify({'ok': False, 'error': 'Producto no encontrado'}), 404

    try:
        with open(products_path, 'w', encoding='utf-8') as fh:
            json.dump(items, fh, ensure_ascii=False, indent=2)
    except Exception as e:
        app.logger.exception('Error saving products.json: %s', e)
        return jsonify({'ok': False, 'error': 'No se pudo guardar'}), 500

    return jsonify({'ok': True, 'product': updated})


@app.route('/productos/<int:prod_id>/json')
def producto_json(prod_id):
    products_path = os.path.join(app.root_path, 'data', 'products.json')
    if not os.path.exists(products_path):
        return jsonify({'ok': False, 'error': 'products.json no encontrado'}), 404
    try:
        with open(products_path, 'r', encoding='utf-8') as fh:
            items = json.load(fh) or []
    except Exception:
        return jsonify({'ok': False, 'error': 'Error leyendo products.json'}), 500
    for it in items:
        try:
            if int(it.get('id')) == int(prod_id):
                return jsonify({'ok': True, 'product': it})
        except Exception:
            continue
    return jsonify({'ok': False, 'error': 'Producto no encontrado'}), 404


@app.route('/inventario')
def inventario():
    # Redirigir a la ruta de inventario principal en caso de accesos con la ruta en español
    return redirect(url_for('inventory'))


@app.route('/contactos')
def contactos():
    items = ['Contacto 1: 63050841', 'Contacto 2: 72554129', 'Contacto: ejemplo@correo.com']
    return render_template('simple_page.html', title='Contactos', heading='Contactos', items=items)


@app.route('/ubicacion')
def ubicacion():
    return render_template('simple_page.html', title='Ubicación', heading='Ubicación', message='Dirección: Av. Cochabamba- al frente de la inglesia jesus obrero - galeria - Piso 1')


@app.route('/galeria')
def galeria():
    items = [
        '/static/img/WhatsApp Image 2026-02-02 at 08.57.22.jpeg',
        '/static/videos/seoul1.mp4',
        '/static/videos/seoul2.mp4',
        '/static/videos/seoul3.mp4',
    ]
    return render_template('simple_page.html', title='Galería', heading='Galería', items=items)


@app.route('/reservas')
@login_required
def reservas():
    # Prefer persisted reservations if present, otherwise show demo data
    items = load_reservations()
    if not items:
        items = [
            {
                'id': 'R-20260201-01',
                'customer': 'Sra. García',
                'contact': '+591 7123-4567',
                'email': 'garcia@example.com',
                'service': 'Grabación de voz - Demo',
                'date': '2026-02-01T10:00:00',
                'room': 'Sala A',
                'duration_minutes': 90,
                'status': 'pending',
                'notes': 'Traer guion, prueba de mic previa'
            },
            {
                'id': 'R-20260202-02',
                'customer': 'Sr. Martínez',
                'contact': '+591 7988-1122',
                'email': 'martinez@example.com',
                'service': 'Sesión karaoke privada',
                'date': '2026-02-02T15:00:00',
                'room': 'Sala VIP',
                'duration_minutes': 120,
                'status': 'confirmed',
                'notes': 'Requiere lista de canciones y catering'
            }
        ]

    summary = {
        'total': len(items),
        'pending': sum(1 for r in items if r.get('status') == 'pending'),
        'confirmed': sum(1 for r in items if r.get('status') == 'confirmed')
    }
    return render_template('simple_page.html', title='Reservas', heading='Reservas / Citas', items=items, summary=summary, show_form=True)


@app.route('/api/reservations/confirm', methods=['POST'])
@login_required
def api_reservations_confirm():
    data = request.get_json() or {}
    rid = data.get('id') or data.get('reservation_id')
    if not rid:
        return jsonify({'error': 'missing id'}), 400
    try:
        items = load_reservations()
        changed = False
        target_room = None
        for r in items:
            if r.get('id') == rid:
                r['status'] = 'confirmed'
                r['confirmed_at'] = datetime.utcnow().isoformat() + 'Z'
                changed = True
                target_room = r.get('room')
                break
        if changed:
            save_reservations(items)
            try:
                emit_room = None
                try:
                    emit_room = normalize_room(target_room) if not isinstance(target_room, int) else int(target_room)
                except Exception:
                    emit_room = None
                if emit_room:
                    socketio.emit('reservation_update', {'action': 'confirmed', 'id': rid}, room=f"room_{emit_room}")
            except Exception:
                app.logger.exception('Failed emitting reservation_confirmed')
            return jsonify({'ok': True, 'id': rid})
        return jsonify({'error': 'not found'}), 404
    except Exception:
        app.logger.exception('Error confirming reservation')
        return jsonify({'error': 'server error'}), 500


@app.route('/api/reservations/cancel', methods=['POST'])
@login_required
def api_reservations_cancel():
    data = request.get_json() or {}
    rid = data.get('id') or data.get('reservation_id')
    if not rid:
        return jsonify({'error': 'missing id'}), 400
    try:
        items = load_reservations()
        changed = False
        target_room = None
        for r in items:
            if r.get('id') == rid:
                r['status'] = 'cancelled'
                r['cancelled_at'] = datetime.utcnow().isoformat() + 'Z'
                changed = True
                target_room = r.get('room')
                break
        if changed:
            save_reservations(items)
            try:
                emit_room = None
                try:
                    emit_room = normalize_room(target_room) if not isinstance(target_room, int) else int(target_room)
                except Exception:
                    emit_room = None
                if emit_room:
                    socketio.emit('reservation_update', {'action': 'cancelled', 'id': rid}, room=f"room_{emit_room}")
            except Exception:
                app.logger.exception('Failed emitting reservation_cancelled')
            return jsonify({'ok': True, 'id': rid})
        return jsonify({'error': 'not found'}), 404
    except Exception:
        app.logger.exception('Error cancelling reservation')
        return jsonify({'error': 'server error'}), 500


@app.route('/api/reservations/update', methods=['POST'])
@login_required
def api_reservations_update():
    """Actualizar una reserva existente. Se espera JSON con 'id' y campos opcionales.
    Devuelve la reserva actualizada.
    """
    data = request.get_json() or request.form or {}
    rid = (data.get('id') or data.get('reservation_id') or '').strip()
    if not rid:
        return jsonify({'error': 'missing id'}), 400
    try:
        items = load_reservations()
        changed = False
        updated = None
        for r in items:
            if r.get('id') == rid:
                # campos actualizables
                for fld in ('customer', 'contact', 'email', 'service', 'date', 'notes'):
                    if fld in data:
                        r[fld] = (data.get(fld) or '').strip()
                if 'duration_minutes' in data:
                    try:
                        r['duration_minutes'] = int(data.get('duration_minutes') or r.get('duration_minutes') or 60)
                    except Exception:
                        pass
                # permitir actualizar sala si es válida
                if 'room' in data or 'room_number' in data:
                    room_raw = data.get('room') or data.get('room_number')
                    rn = normalize_room(room_raw)
                    if rn is None:
                        return jsonify({'error': 'invalid room'}), 400
                    r['room'] = rn

                r['updated_at'] = datetime.utcnow().isoformat() + 'Z'
                changed = True
                updated = r
                break
        if not changed:
            return jsonify({'error': 'not found'}), 404
        save_reservations(items)
        # emitir actualización a sala y notificar admins
        try:
            emit_room = normalize_room(updated.get('room')) if not isinstance(updated.get('room'), int) else int(updated.get('room'))
        except Exception:
            emit_room = None
        try:
            if emit_room:
                socketio.emit('reservation_update', {'action': 'updated', 'reservation': updated}, room=f'room_{emit_room}')
        except Exception:
            app.logger.exception('Failed emitting reservation_update for update')

        try:
            socketio.emit('notification', {'message': f'Reserva actualizada: {updated.get("customer")} ({rid})', 'type': 'info'}, room='admins')
        except Exception:
            app.logger.exception('Failed emitting admin notification for reservation update')

        return jsonify({'ok': True, 'reservation': updated})
    except Exception:
        app.logger.exception('Error updating reservation')
        return jsonify({'error': 'server error'}), 500


@app.route('/api/reservations/create', methods=['POST'])
@login_required
def api_reservations_create():
    # Accept JSON body or form-encoded
    data = request.get_json() or request.form or {}
    customer = (data.get('customer') or data.get('customer_name') or '').strip()
    contact = (data.get('contact') or data.get('phone') or '').strip()
    email = (data.get('email') or '').strip() or None
    service = (data.get('service') or 'Reserva').strip()
    date_raw = (data.get('date') or '').strip()
    room_raw = (data.get('room') or data.get('room_number') or '')
    # Normalizar y validar sala
    room_norm = normalize_room(room_raw)
    if room_norm is None:
        return jsonify({'error': 'invalid room'}), 400
    room = room_norm
    try:
        duration = int(data.get('duration_minutes') or data.get('duration') or 60)
    except Exception:
        duration = 60

    if not customer or not date_raw:
        return jsonify({'error': 'missing fields'}), 400

    rid = f"R-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(3)}"
    res = {
        'id': rid,
        'customer': customer,
        'contact': contact,
        'email': email,
        'service': service,
        'date': date_raw,
        'room': room,
        'duration_minutes': duration,
        'status': 'pending',
        'notes': (data.get('notes') or '')
    }
    try:
        items = load_reservations()
        items.insert(0, res)
        save_reservations(items)
        # emit to room and notify admins
        try:
            socketio.emit('reservation_update', {'action': 'created', 'reservation': res}, room=f'room_{room}')
        except Exception:
            app.logger.exception('Failed emitting reservation created to room')
        try:
            socketio.emit('notification', {'message': f'Nueva reserva: {customer} ({rid})', 'type': 'info'}, room='admins')
        except Exception:
            app.logger.exception('Failed emitting admin notification for reservation create')

        return jsonify({'ok': True, 'reservation': res})
    except Exception:
        app.logger.exception('Error creating reservation')
        return jsonify({'error': 'server error'}), 500


@app.route('/salas')
def salas():
    items = ['Sala A', 'Sala B', 'Sala VIP']
    return render_template('simple_page.html', title='Salas', heading='Salas', items=items)


@app.route('/precios')
def precios():
    # Mostrar precios en Bolivianos; entradas generales a 35 Bs
    items = ['Entrada general: 35 Bs']
    return render_template('simple_page.html', title='Precios', heading='Precios', items=items)


@app.route('/_show_base_url')
def _show_base_url():
    # Endpoint de diagnóstico para mostrar la URL externa generada
    try:
        login_url = url_for('login', _external=True)
    except Exception as e:
        login_url = f'error generando url: {e}'
    info = {
        'login_url': login_url,
        'server_name': app.config.get('SERVER_NAME'),
        'preferred_scheme': app.config.get('PREFERRED_URL_SCHEME')
    }
    return (f"LOGIN_URL: {info['login_url']}\n"
            f"SERVER_NAME: {info['server_name']}\n"
            f"PREFERRED_URL_SCHEME: {info['preferred_scheme']}\n"), 200, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/_debug_layout')
def _debug_layout():
    # Renderizar la plantilla base `layout.html` para depuración
    # Forzamos usuario nulo para ver la versión no autenticada
    return render_template('layout.html', user=None)


@app.route('/_debug_invoice')
def _debug_invoice():
    """Ruta de depuración: crea un ticket de prueba y redirige a la vista de factura.
    Útil para comprobar que la plantilla `invoice.html` se renderiza correctamente
    sin depender del formulario de compra o de la autenticación.
    """
    try:
        t = Ticket(
            buyer_name='Cliente Prueba',
            buyer_id='00000000',
            price=float(app.config.get('DEFAULT_TICKET_PRICE', 35.0)),
            room_number=1,
            entry_time=datetime.now(timezone.utc),
            exit_time=None,
            promo=False,
            snacks=False,
            promo_type=None,
            snacks_list=None,
            created_by=(session.get('user') or {}).get('username') if session.get('user') else None,
        )
        db.session.add(t)
        db.session.commit()
        return redirect(url_for('invoice_ticket', ticket_id=t.id))
    except Exception as e:
        return f"Error creando ticket de prueba: {e}", 500


@app.route('/invoice/<int:ticket_id>')
def invoice_ticket(ticket_id):
    # Mostrar factura detallada del ticket
    t = Ticket.query.get(ticket_id)
    if not t:
        return "Ticket no encontrado.", 404

    snack_items = []
    snack_total = 0.0
    if t.snacks_list:
        # intentar parsear JSON primero
        try:
            possible = json.loads(t.snacks_list)
            if isinstance(possible, list):
                for it in possible:
                    pid = None
                    name = None
                    qty = 1
                    price = 0.0
                    image = None
                    if isinstance(it, dict):
                        try:
                            pid = int(it.get('id') or 0) or None
                        except Exception:
                            pid = None
                        name = it.get('name') or None
                        try:
                            qty = int(it.get('qty') or 1)
                        except Exception:
                            qty = 1
                        try:
                            price = float(it.get('price') or 0.0)
                        except Exception:
                            price = 0.0
                        image = it.get('image') or None
                    else:
                        # item could be a plain string
                        name = str(it)

                    # Priorizar datos guardados en el ticket; solo si faltan, consultar tabla Product
                    if (not name or price == 0.0 or not image) and pid:
                        try:
                            prod = Product.query.get(pid)
                            if prod:
                                if not name:
                                    name = prod.name
                                if price == 0.0:
                                    # Product model uses .price; data JSON may have price_bs
                                    try:
                                        price = float(getattr(prod, 'price', 0.0) or 0.0)
                                    except Exception:
                                        price = 0.0
                                if not image:
                                    # try to read image from products.json map later
                                    image = None
                        except Exception:
                            pass

                    snack_total += (price or 0.0) * (qty or 1)
                    snack_items.append({'id': pid, 'name': name or '', 'qty': qty, 'price': price or 0.0, 'image': image})
        except Exception:
            # fallback: treat as CSV of names
            names = [x.strip() for x in (t.snacks_list or '').split(',') if x.strip()]
            for n in names:
                snack_items.append({'id': None, 'name': n, 'qty': 1, 'price': 0.0})

    # Enriquecer items con imagen si está disponible en data/products.json
    try:
        prod_map = {int(p.get('id')): p for p in load_products()}
        for it in snack_items:
            try:
                pid = int(it.get('id') or 0)
                pinfo = prod_map.get(pid)
                if pinfo:
                    it['image'] = pinfo.get('image')
                else:
                    it['image'] = None
            except Exception:
                it['image'] = None
    except Exception:
        pass

    base_price = float(t.price) - float(snack_total)
    # determinar tipo de factura (heladeria vs karaoke vs general)
    try:
        if ticket_is_heladeria(t):
            inv_kind = 'heladeria'
        elif getattr(t, 'room_number', 0) and int(getattr(t, 'room_number', 0)) > 0:
            inv_kind = 'karaoke'
        else:
            inv_kind = 'general'
    except Exception:
        inv_kind = 'general'

    # número de factura legible (reservar/recuperar desde mapping persistente)
    invoice_number = get_or_create_invoice_number(t.id, inv_kind)
    # fecha de emisión (automática). Vencimiento eliminado por requerimiento.
    issued_at = t.created_at
    # impuestos (tax rate en configuración, p.ej. 0.13 para 13%)
    tax_rate = float(app.config.get('TAX_RATE', 0.0) or 0.0)
    taxable_amount = base_price + float(snack_total)
    tax_amount = round(taxable_amount * tax_rate, 2)
    total_with_tax = round(taxable_amount + tax_amount, 2)

    # Si el ticket es de heladería, usar plantilla específica
    try:
        if ticket_is_heladeria(t):
            # Mostrar solo los items de heladería en esta factura
            try:
                hel_ids = get_heladeria_product_ids()
                hel_snack_items = [it for it in snack_items if it.get('id') and int(it.get('id') or 0) in hel_ids]
            except Exception:
                hel_snack_items = snack_items
            # Si no hay items heladería (ej. datos inconsistentes), fallback a la factura normal
            if not hel_snack_items:
                return render_template('invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, base_price=base_price, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_available=is_pdf_available())
            return render_template('heladeria_invoice.html', ticket=t, snack_items=hel_snack_items, snack_total=sum(it.get('price',0.0)*int(it.get('qty',1)) for it in hel_snack_items), invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax)
    except Exception:
        pass

    return render_template('invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, base_price=base_price, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_available=is_pdf_available())


@app.route('/invoice/<int:ticket_id>/pdf')
def invoice_pdf(ticket_id):
    # Generar y servir PDF de la factura usando wkhtmltopdf via pdfkit
    t = Ticket.query.get(ticket_id)
    if not t:
        return "Ticket no encontrado.", 404

    # Reconstruir detalle de snacks
    snack_items = []
    snack_total = 0.0
    if t.snacks_list:
        try:
            possible = json.loads(t.snacks_list)
            if isinstance(possible, list):
                for it in possible:
                    pid = None
                    name = None
                    qty = 1
                    price = 0.0
                    image = None
                    if isinstance(it, dict):
                        try:
                            pid = int(it.get('id') or 0) or None
                        except Exception:
                            pid = None
                        name = it.get('name') or None
                        try:
                            qty = int(it.get('qty') or 1)
                        except Exception:
                            qty = 1
                        try:
                            price = float(it.get('price') or 0.0)
                        except Exception:
                            price = 0.0
                        image = it.get('image') or None
                    else:
                        name = str(it)

                    if (not name or price == 0.0 or not image) and pid:
                        try:
                            prod = Product.query.get(pid)
                            if prod:
                                if not name:
                                    name = prod.name
                                if price == 0.0:
                                    try:
                                        price = float(getattr(prod, 'price', 0.0) or 0.0)
                                    except Exception:
                                        price = 0.0
                                if not image:
                                    image = None
                        except Exception:
                            pass

                    snack_total += (price or 0.0) * (qty or 1)
                    snack_items.append({'id': pid, 'name': name or '', 'qty': qty, 'price': price or 0.0, 'image': image})
        except Exception:
            names = [x.strip() for x in (t.snacks_list or '').split(',') if x.strip()]
            for n in names:
                snack_items.append({'id': None, 'name': n, 'qty': 1, 'price': 0.0})

    base_price = float(t.price) - float(snack_total)
    # determinar tipo de factura para PDF también
    try:
        if ticket_is_heladeria(t):
            pdf_inv_kind = 'heladeria'
        elif getattr(t, 'room_number', 0) and int(getattr(t, 'room_number', 0)) > 0:
            pdf_inv_kind = 'karaoke'
        else:
            pdf_inv_kind = 'general'
    except Exception:
        pdf_inv_kind = 'general'
    invoice_number = get_or_create_invoice_number(t.id, pdf_inv_kind)
    issued_at = t.created_at
    tax_rate = float(app.config.get('TAX_RATE', 0.0) or 0.0)
    taxable_amount = base_price + float(snack_total)
    tax_amount = round(taxable_amount * tax_rate, 2)
    total_with_tax = round(taxable_amount + tax_amount, 2)

    # Si es heladería, renderizar la plantilla específica para PDF también
    try:
        if ticket_is_heladeria(t):
            # Enriquecer con imágenes antes de renderizar PDF
            try:
                prod_map = {int(p.get('id')): p for p in load_products()}
                for it in snack_items:
                    try:
                        pid = int(it.get('id') or 0)
                        pinfo = prod_map.get(pid)
                        if pinfo:
                            it['image'] = pinfo.get('image')
                        else:
                            it['image'] = None
                    except Exception:
                        it['image'] = None
            except Exception:
                pass
            # Filtrar solo items de heladería para el PDF
            try:
                hel_ids = get_heladeria_product_ids()
                hel_snack_items = [it for it in snack_items if it.get('id') and int(it.get('id') or 0) in hel_ids]
            except Exception:
                hel_snack_items = snack_items
            if not hel_snack_items:
                rendered = render_template('invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, base_price=base_price, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_render=True)
            else:
                rendered = render_template('heladeria_invoice.html', ticket=t, snack_items=hel_snack_items, snack_total=sum(it.get('price',0.0)*int(it.get('qty',1)) for it in hel_snack_items), invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_render=True)
        else:
            rendered = render_template('invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, base_price=base_price, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_render=True)
    except Exception:
        rendered = render_template('invoice.html', ticket=t, snack_items=snack_items, snack_total=snack_total, base_price=base_price, invoice_number=invoice_number, issued_at=issued_at, tax_rate=tax_rate, tax_amount=tax_amount, total_with_tax=total_with_tax, pdf_render=True)

    # Reescribir rutas '/static/...' a file:/// absolutas para wkhtmltopdf cuando se genera desde archivo
    try:
        import re
        def _abs_static(match):
            attr = match.group(1)
            rel = match.group(2)
            # construir ruta absoluta al archivo en disco
            local_path = os.path.join(app.root_path, rel.lstrip('/').replace('/', os.sep))
            local_path = os.path.abspath(local_path)
            # Normalizar para file:// URI en Windows
            file_uri = 'file:///' + local_path.replace('\\', '/')
            return f"{attr}=\"{file_uri}\""

        rendered = re.sub(r"(href|src)=(?:\"|')(/static/[^\"']+)(?:\"|')", _abs_static, rendered)
    except Exception:
        pass

    # Intentar importar pdfkit de forma segura
    try:
        import importlib
        pdfkit = importlib.import_module('pdfkit')
    except Exception:
        try:
            flash('pdfkit no está instalado. Instala pdfkit y wkhtmltopdf para habilitar descarga PDF.')
        except Exception:
            pass
        return redirect(url_for('invoice_ticket', ticket_id=t.id))

    # Detectar ejecutable wkhtmltopdf y configurar pdfkit
    wk_path = detect_wkhtmltopdf()
    config = None
    if wk_path:
        try:
            config = pdfkit.configuration(wkhtmltopdf=wk_path)
        except Exception:
            config = None
    else:
        try:
            flash('Advertencia: wkhtmltopdf no encontrado. Instala el binario o configura WKHTMLTOPDF_PATH o ajústalo en Admin > Settings.')
        except Exception:
            pass

    # Generar PDF
    try:
        # Opciones para permitir acceso a archivos locales y tolerar errores de carga de recursos externos
        # Opciones por defecto para wkhtmltopdf: acceso local, manejo de errores y formato de página
        options = {
            'enable-local-file-access': '',
            'load-error-handling': 'ignore',
            'no-stop-slow-scripts': '',
            'page-size': 'A4',
            'orientation': 'Portrait',
            'margin-top': '10mm',
            'margin-bottom': '10mm',
            'margin-left': '10mm',
            'margin-right': '10mm'
        }
        # Si la factura es de heladería, ajustar opciones para impresión térmica (p.ej. 80mm)
        try:
            if ticket_is_heladeria(t) or (pdf_inv_kind == 'heladeria'):
                # wkhtmltopdf acepta --page-width/--page-height en mm
                options.update({
                    'page-width': '80mm',
                    'page-height': '200mm',
                    'margin-top': '2mm',
                    'margin-bottom': '2mm',
                    'margin-left': '2mm',
                    'margin-right': '2mm',
                })
                # eliminar page-size por si entra en conflicto
                if 'page-size' in options:
                    del options['page-size']
        except Exception:
            pass
        # Escribir HTML temporal en disco y usar from_file para resolver correctamente rutas relativas
        import tempfile
        tmp_dir = os.path.join(app.root_path, 'static')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f'invoice_{t.id}.html')
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            fh.write(rendered)
        try:
            # Ejecutar wkhtmltopdf manualmente para capturar PDF aun si devuelve código != 0
            import subprocess
            tmp_pdf = tmp_path + '.pdf'
            cmd = [wk_path or 'wkhtmltopdf', '--enable-local-file-access']
            # añadir opciones adicionales compatibles
            for k, v in options.items():
                if v is None or v == '':
                    cmd.append(f'--{k}')
                else:
                    cmd.extend([f'--{k}', str(v)])
            cmd.extend([tmp_path, tmp_pdf])
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0:
                with open(tmp_pdf, 'rb') as fh:
                    pdf = fh.read()
            else:
                # si wkhtmltopdf devolvió error pero produjo el archivo, úsalo
                if os.path.exists(tmp_pdf):
                    try:
                        with open(tmp_pdf, 'rb') as fh:
                            pdf = fh.read()
                    except Exception:
                        raise
                else:
                    # re-lanzar con stderr para logging
                    raise RuntimeError('wkhtmltopdf failed: ' + (proc.stderr.decode('utf-8', errors='replace') or ''))
            # eliminar PDF temporal
            try:
                if os.path.exists(tmp_pdf):
                    os.remove(tmp_pdf)
            except Exception:
                pass
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        response = make_response(pdf)
        response.headers['Content-Type'] = 'application/pdf'
        response.headers['Content-Disposition'] = f'attachment; filename=ticket_{invoice_number}.pdf'
        return response
    except Exception:
        # Log del error para depuración y notificación al usuario
        try:
            app.logger.exception('Error generando PDF de factura para ticket %s', t.id)
        except Exception:
            pass
        try:
            flash('No se pudo generar el PDF (wkhtmltopdf/pdfkit). Imprime desde el navegador o configura wkhtmltopdf.')
        except Exception:
            pass
        return redirect(url_for('invoice_ticket', ticket_id=t.id))


@app.route('/_wkhtmltopdf')
def _wkhtmltopdf():
    # Endpoint diagnóstico que muestra la ruta detectada o instrucciones
    try:
        def detect():
            env_path = os.environ.get('WKHTMLTOPDF_PATH')
            if env_path and os.path.exists(env_path):
                return env_path
            if platform.system().lower().startswith('win'):
                candidates = [
                    r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
                    r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
                ]
            else:
                candidates = ['/usr/local/bin/wkhtmltopdf', '/usr/bin/wkhtmltopdf']
            for p in candidates:
                if os.path.exists(p):
                    return p
            which_path = shutil.which('wkhtmltopdf')
            if which_path:
                return which_path
            return None

        found = detect()
        if found:
            return f"wkhtmltopdf encontrado: {found}", 200, {'Content-Type': 'text/plain; charset=utf-8'}
        else:
            return ("wkhtmltopdf no encontrado. Instala desde https://wkhtmltopdf.org/ "
                    "o configura la variable de entorno WKHTMLTOPDF_PATH con la ruta al ejecutable."), 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception:
        return "Error detectando wkhtmltopdf.", 500, {'Content-Type': 'text/plain; charset=utf-8'}


@app.route('/eventos')
def eventos():
    items = ['Evento 1: Concierto demo - 2026-03-10', 'Evento 2: Karaoke Night - 2026-03-20']
    return render_template('simple_page.html', title='Eventos', heading='Eventos', items=items)


@app.route('/heladeria/report')
@login_required
def heladeria_report():
    # Permitir solo administradores por ahora
    user = session.get('user') or {}
    if not user.get('is_admin'):
        abort(403)

    # parámetros: start, end (YYYY-MM-DD), group=day|month
    start_s = request.args.get('start')
    end_s = request.args.get('end')
    group = request.args.get('group') or 'day'
    start = None
    end = None
    try:
        if start_s:
            start = datetime.strptime(start_s, '%Y-%m-%d')
        if end_s:
            # incluir el día completo
            end = datetime.strptime(end_s, '%Y-%m-%d') + timedelta(hours=23, minutes=59, seconds=59)
    except Exception:
        start = None
        end = None

    # Usar el modelo separado `HeladeriaOrder` si existe; fallback a tickets
    try:
        report = compute_heladeria_sales_orders(start=start, end=end, group_by=group)
    except Exception:
        report = compute_heladeria_sales(start=start, end=end, group_by=group)
    return render_template('heladeria_report.html', report=report)


@app.route('/heladeria/print_direct/<int:ticket_id>')
@login_required
def heladeria_print_direct(ticket_id):
    """Genera el PDF de la factura y lo envía a la impresora local (Windows: ShellExecute; Unix: lp/lpr)."""
    try:
        t = Ticket.query.get(ticket_id)
        # support old tickets and new HeladeriaOrder ids: if not a Ticket, try HeladeriaOrder
        if not t:
            ho = HeladeriaOrder.query.get(ticket_id)
            if ho:
                # render heladeria invoice PDF for order
                resp = heladeria_invoice_pdf(ho.id)
                if not isinstance(resp, Response) or not resp.headers.get('Content-Type', '').startswith('application/pdf'):
                    flash('No se pudo generar el PDF para imprimir. Verifica wkhtmltopdf/pdfkit.', 'danger')
                    return redirect(url_for('heladeria'))
                pdf_bytes = resp.get_data()
                tmp_dir = os.path.join(app.root_path, 'tmp')
                os.makedirs(tmp_dir, exist_ok=True)
                tmp_pdf = os.path.join(tmp_dir, f'hel_print_{ho.id}.pdf')
                with open(tmp_pdf, 'wb') as fh:
                    fh.write(pdf_bytes)
                try:
                    if os.name == 'nt':
                        os.startfile(tmp_pdf, 'print')
                    else:
                        import subprocess
                        subprocess.run(['lp', tmp_pdf])
                except Exception:
                    app.logger.exception('Failed sending PDF to printer')
                    flash('Error imprimiendo PDF.', 'danger')
                    return redirect(url_for('heladeria'))
                flash('Impresión enviada.', 'success')
                return redirect(url_for('heladeria'))
            flash('Ticket no encontrado', 'danger')
            return redirect(url_for('heladeria'))
        if not t:
            flash('Ticket no encontrado', 'danger')
            return redirect(url_for('heladeria'))
        if not ticket_is_heladeria(t):
            flash('Este ticket no corresponde a una factura de heladería.', 'danger')
            return redirect(url_for('heladeria'))

        # Llamar a invoice_pdf para generar el PDF en memoria
        resp = invoice_pdf(ticket_id)
        if not isinstance(resp, Response) or not resp.headers.get('Content-Type', '').startswith('application/pdf'):
            flash('No se pudo generar el PDF para imprimir. Verifica wkhtmltopdf/pdfkit.', 'danger')
            return redirect(url_for('heladeria'))

        pdf_bytes = resp.get_data()
        tmp_dir = os.path.join(app.root_path, 'tmp')
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_pdf = os.path.join(tmp_dir, f'hel_print_{ticket_id}.pdf')
        with open(tmp_pdf, 'wb') as fh:
            fh.write(pdf_bytes)

        # Enviar a impresora según el sistema
        if platform.system().lower().startswith('win'):
            try:
                try:
                    import win32api  # type: ignore[reportMissingModuleSource]
                    win32api.ShellExecute(0, 'print', tmp_pdf, None, '.', 0)
                    flash('Enviado a impresora por defecto (Windows).', 'success')
                    return redirect(url_for('heladeria'))
                except Exception:
                    subprocess.run(['cmd', '/c', 'start', '/min', '/wait', tmp_pdf], check=False)
                    flash('Impresión enviada (método alternativo Windows).', 'success')
                    return redirect(url_for('heladeria'))
            except Exception:
                app.logger.exception('Failed printing on Windows')
                flash('No se pudo enviar a la impresora en Windows.', 'danger')
                return redirect(url_for('heladeria'))
        else:
            try:
                subprocess.run(['lp', tmp_pdf], check=True)
                flash('Enviado a impresora (lp).', 'success')
                return redirect(url_for('heladeria'))
            except Exception:
                try:
                    subprocess.run(['lpr', tmp_pdf], check=True)
                    flash('Enviado a impresora (lpr).', 'success')
                    return redirect(url_for('heladeria'))
                except Exception:
                    app.logger.exception('Failed printing on Unix')
                    flash('No se pudo enviar a la impresora.', 'danger')
                    return redirect(url_for('heladeria'))
    except Exception:
        app.logger.exception('heladeria_print_direct failed')
        flash('Error imprimiendo directamente.', 'danger')
        return redirect(url_for('heladeria'))


@app.route('/asistencia')
@login_required
def asistencia():
    # ensure attendance schema up-to-date before queries
    ensure_attendance_columns()
    user = session.get('user') or {}
    username = user.get('username')
    is_admin = bool(user.get('is_admin'))
    # show recent attendance: admins see all, staff see own
    try:
        if is_admin:
            try:
                allowed_roles = ('Admin', 'Staff', 'Personal Nuevo')
                recent = Attendance.query.filter(Attendance.role.in_(allowed_roles)).order_by(Attendance.date.desc(), Attendance.check_in.desc()).limit(200).all()
            except OperationalError:
                # fallback: select without role column
                engine = db.get_engine(app)
                q = "SELECT id,user_id,username,date,check_in,check_out,duration_minutes,note,created_by,created_at FROM attendance ORDER BY date DESC, check_in DESC LIMIT 200"
                rows = engine.execute(text(q)).fetchall()
                recent = [SimpleNamespace(**dict(r)) for r in rows]
        else:
            # show only this user's records
            u = User.query.filter_by(username=username).first()
            if u:
                try:
                    recent = Attendance.query.filter_by(user_id=u.id).order_by(Attendance.date.desc(), Attendance.check_in.desc()).limit(200).all()
                except OperationalError:
                    engine = getattr(db, 'engine', None) or db.get_engine(app)
                    q = "SELECT id,user_id,username,date,check_in,check_out,duration_minutes,note,created_by,created_at FROM attendance WHERE user_id = :uid ORDER BY date DESC, check_in DESC LIMIT 200"
                    rows = engine.execute(text(q), {'uid': u.id}).fetchall()
                    recent = [SimpleNamespace(**dict(r)) for r in rows]
            else:
                recent = []
    except Exception:
        recent = []

    # find today's open record for current user (if any)
    today = date.today()
    open_record = None
    try:
        if not is_admin and username:
            u = User.query.filter_by(username=username).first()
        if u:
            try:
                open_record = Attendance.query.filter_by(user_id=u.id, date=today, check_out=None).order_by(Attendance.check_in.desc()).first()
            except OperationalError:
                engine = getattr(db, 'engine', None) or db.get_engine(app)
                q2 = "SELECT id,user_id,username,date,check_in,check_out,duration_minutes,note,created_by,created_at FROM attendance WHERE user_id = :uid AND date = :d AND check_out IS NULL ORDER BY check_in DESC LIMIT 1"
                rows2 = engine.execute(text(q2), {'uid': u.id, 'd': today}).fetchall()
                if rows2:
                    open_record = SimpleNamespace(**dict(rows2[0]))
                else:
                    open_record = None
    except Exception:
        open_record = None

    return render_template('asistencia.html', title='Asistencia', heading='Asistencia (admin/personal)', recent=recent, open_record=open_record, is_admin=is_admin)


@app.route('/asistencia/checkin', methods=['POST'])
@login_required
def asistencia_checkin():
    # ensure attendance table has required columns (migration safety)
    ensure_attendance_columns()
    user = session.get('user') or {}
    username = user.get('username')
    try:
        u = User.query.filter_by(username=username).first()
    except Exception:
        u = None
    if not u:
        # try to auto-create user in development
        u = ensure_user_exists(username)
    if not u:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 400
    # prevent duplicate open record for today
    today = date.today()
    try:
        existing = Attendance.query.filter_by(user_id=u.id, date=today, check_out=None).first()
    except OperationalError:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        q_exist = "SELECT id,user_id,username,date,check_in,check_out,duration_minutes,note,created_by,created_at FROM attendance WHERE user_id = :uid AND date = :d AND check_out IS NULL ORDER BY check_in DESC LIMIT 1"
        rows_exist = engine.execute(text(q_exist), {'uid': u.id, 'd': today}).fetchall()
        existing = SimpleNamespace(**dict(rows_exist[0])) if rows_exist else None
    if existing:
        return jsonify({'success': False, 'error': 'Ya tienes entrada registrada sin salida.'}), 400
    now = datetime.now(timezone.utc)
    # include role only if DB table has the column (migration-safe)
    engine = getattr(db, 'engine', None) or db.get_engine(app)
    try:
        cols = [c['name'] for c in inspect(engine).get_columns('attendance')]
    except Exception:
        cols = []
    role_val = 'Admin' if getattr(u, 'is_admin', False) else (getattr(u, 'role', None) or 'Staff')
    if 'role' in cols:
        a = Attendance(user_id=u.id, username=u.username, role=role_val, date=today, check_in=now, created_by=username, created_at=datetime.now(timezone.utc))
    else:
        a = Attendance(user_id=u.id, username=u.username, date=today, check_in=now, created_by=username, created_at=datetime.now(timezone.utc))
    try:
        db.session.add(a)
        db.session.commit()
        create_audit(username, 'checkin', 'attendance', a.id, f'checkin at {now.isoformat()}')
        app.logger.info('Attendance created: %s by %s', a.id, username)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'record': a.to_dict()})
        flash('Entrada registrada.')
        return redirect(url_for('asistencia'))
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        app.logger.exception('Error creating attendance')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash('Error registrando entrada: ' + str(e))
        return redirect(url_for('asistencia'))


@app.route('/asistencia/checkout', methods=['POST'])
@login_required
def asistencia_checkout():
    ensure_attendance_columns()
    user = session.get('user') or {}
    username = user.get('username')
    try:
        u = User.query.filter_by(username=username).first()
    except Exception:
        u = None
    if not u:
        u = ensure_user_exists(username)
    if not u:
        return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 400
    today = date.today()
    try:
        rec = Attendance.query.filter_by(user_id=u.id, date=today, check_out=None).order_by(Attendance.check_in.desc()).first()
    except OperationalError:
        engine = getattr(db, 'engine', None) or db.get_engine(app)
        q_rec = "SELECT id,user_id,username,date,check_in,check_out,duration_minutes,note,created_by,created_at FROM attendance WHERE user_id = :uid AND date = :d AND check_out IS NULL ORDER BY check_in DESC LIMIT 1"
        rows_rec = engine.execute(text(q_rec), {'uid': u.id, 'd': today}).fetchall()
        rec = SimpleNamespace(**dict(rows_rec[0])) if rows_rec else None
    if not rec:
        return jsonify({'success': False, 'error': 'No hay registro abierto para hoy.'}), 400
    now = datetime.now(timezone.utc)
    rec.check_out = now
    try:
        delta = now - rec.check_in
        rec.duration_minutes = int(delta.total_seconds() // 60)
    except Exception:
        rec.duration_minutes = None
    try:
        db.session.add(rec)
        db.session.commit()
        create_audit(username, 'checkout', 'attendance', rec.id, f'checkout at {now.isoformat()}')
        app.logger.info('Attendance checked out: %s by %s', rec.id, username)
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': True, 'record': rec.to_dict()})
        flash('Salida registrada.')
        return redirect(url_for('asistencia'))
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        app.logger.exception('Error checking out attendance')
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash('Error registrando salida: ' + str(e))
        return redirect(url_for('asistencia'))


@app.route('/asistencia/export.csv')
@login_required
@admin_required
def asistencia_export():
    # params: from, to (YYYY-MM-DD)
    qs = request.args
    frm = qs.get('from')
    to = qs.get('to')
    q = Attendance.query.order_by(Attendance.date.asc(), Attendance.check_in.asc())
    try:
        if frm:
            d1 = datetime.strptime(frm, '%Y-%m-%d').date()
            q = q.filter(Attendance.date >= d1)
        if to:
            d2 = datetime.strptime(to, '%Y-%m-%d').date()
            q = q.filter(Attendance.date <= d2)
    except Exception:
        pass
    rows = q.all()
    def generate():
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(['id','username','date','check_in','check_out','duration_minutes','note'])
        yield data.getvalue()
        data.seek(0); data.truncate(0)
        for r in rows:
            writer.writerow([r.id, r.username, r.date.isoformat(), r.check_in.isoformat() if r.check_in else '', r.check_out.isoformat() if r.check_out else '', r.duration_minutes or '', r.note or ''])
            yield data.getvalue()
            data.seek(0); data.truncate(0)
    filename = f"asistencia_{frm or 'all'}_{to or 'all'}.csv"
    return Response(generate(), mimetype='text/csv', headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route('/asistencia/<int:att_id>/json', methods=['GET'])
@login_required
@admin_required
def asistencia_record_json(att_id):
    r = Attendance.query.get_or_404(att_id)
    try:
        return jsonify({'ok': True, 'record': r.to_dict()})
    except Exception:
        return jsonify({'ok': False, 'error': 'Error generando JSON'}), 500


@app.route('/asistencia/<int:att_id>/edit', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def asistencia_edit(att_id):
    r = Attendance.query.get_or_404(att_id)
    data = request.form.to_dict() if request.form else (request.get_json() or {})
    # allow editing check_in, check_out, note, username, role
    def _parse_dt(s):
        if not s:
            return None
        try:
            # accept ISO format or space separated
            # support trailing 'Z' by converting to +00:00 for fromisoformat
            ss = s
            if isinstance(ss, str) and ss.endswith('Z'):
                ss = ss[:-1] + '+00:00'
            v = datetime.fromisoformat(ss)
            # normalize: if naive, assume UTC; else convert to UTC
            try:
                if getattr(v, 'tzinfo', None) is None:
                    v = v.replace(tzinfo=timezone.utc)
                else:
                    v = v.astimezone(timezone.utc)
            except Exception:
                pass
            return v
        except Exception:
            try:
                return datetime.strptime(s, '%Y-%m-%d %H:%M')
            except Exception:
                try:
                    # last attempt: parse and assume UTC
                    v2 = datetime.strptime(s, '%Y-%m-%d %H:%M')
                    return v2.replace(tzinfo=timezone.utc)
                except Exception:
                    return None
    try:
        if 'username' in data:
            r.username = data.get('username')
        if 'role' in data:
            r.role = data.get('role')
        if 'note' in data:
            r.note = data.get('note')
        if 'status' in data:
            try:
                r.status = data.get('status')
            except Exception:
                pass
        if 'check_in' in data:
            v = _parse_dt(data.get('check_in'))
            if v:
                r.check_in = v
        if 'check_out' in data:
            v2 = _parse_dt(data.get('check_out'))
            r.check_out = v2
        # recalc duration if both present
        try:
            if r.check_in and r.check_out:
                delta = r.check_out - r.check_in
                r.duration_minutes = int(delta.total_seconds() // 60)
            else:
                r.duration_minutes = None
        except Exception:
            r.duration_minutes = None
        db.session.add(r)
        db.session.commit()
        create_audit(session.get('user', {}).get('username'), 'edit_attendance', 'attendance', r.id, f'Edited attendance {r.id}')
        return jsonify({'ok': True, 'record': r.to_dict()})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/asistencia/<int:att_id>/delete', methods=['POST'])
@login_required
@admin_required
@csrf_protect
def asistencia_delete(att_id):
    r = Attendance.query.get_or_404(att_id)
    try:
        db.session.delete(r)
        db.session.commit()
        create_audit(session.get('user', {}).get('username'), 'delete_attendance', 'attendance', att_id, f'Deleted attendance {att_id}')
        return jsonify({'ok': True})
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({'ok': False, 'error': str(e)}), 500

if __name__ == '__main__':
    # Escuchar en 0.0.0.0 para permitir acceso desde otros dispositivos en la red local
    # En desarrollo use el servidor integrado (no recomendado en producción).
    # Para producción puede arrancar con Waitress poniendo la variable
    # de entorno USE_WAITRESS=1 (ej: PowerShell: $env:USE_WAITRESS='1').
    # Crear tablas automáticamente en desarrollo si FLASK_CREATE_DB != '0'
    if os.environ.get('FLASK_CREATE_DB', '1') != '0':
        try:
            with app.app_context():
                db.create_all()
                try:
                    ensure_user_is_admin_column()
                except Exception:
                    pass
        except Exception:
            # No impedir el arranque si falla la creación automática
            pass

    if os.environ.get('USE_WAITRESS') == '1':
        try:
            from waitress import serve  # type: ignore[reportMissingModuleSource]
        except Exception:
            raise RuntimeError("waitress no está instalado. Instale con: pip install waitress")
        # Se arranca con waitress (producción). No se realiza chequeos adicionales aquí.
        # Ajustes recomendados para producción: aumentar threads y backlog
        # si observa advertencias sobre 'Task queue depth' en Waitress.
        serve(
            app,
            host=os.environ.get('HOST', '0.0.0.0'),
            port=int(os.environ.get('PORT', 3000)),
            threads=int(os.environ.get('WAITRESS_THREADS', 8)),
            backlog=int(os.environ.get('WAITRESS_BACKLOG', 100)),
            channel_timeout=int(os.environ.get('WAITRESS_CHANNEL_TIMEOUT', 30)),
        )
    else:
        # Silenciar el banner/advertencia del servidor de desarrollo que se
        # imprime en stderr por Werkzeug cuando se usa `app.run()`.
        # Redirigimos stderr a devnull solo durante la llamada a app.run().
        # Allow showing server logs when SHOW_SERVER_LOGS=1 is set in env
        show_logs = os.environ.get('SHOW_SERVER_LOGS', '0').lower() in ('1', 'true', 'yes')
        if os.environ.get('FLASK_CREATE_DB', '1') != '0':
            # Si usamos SQLite, aseguramos que la columna exit_time existe en la tabla ticket
            try:
                with app.app_context():
                    engine = db.get_engine()
                    url = str(engine.url)
                    if url.startswith('sqlite'):
                        res = engine.execute("PRAGMA table_info('ticket')").fetchall()
                        cols = [r[1] for r in res]
                        if 'exit_time' not in cols:
                            try:
                                engine.execute('ALTER TABLE ticket ADD COLUMN exit_time DATETIME')
                            except Exception:
                                pass
                        if 'promo' not in cols:
                            try:
                                engine.execute("ALTER TABLE ticket ADD COLUMN promo INTEGER DEFAULT 0")
                            except Exception:
                                pass
                        if 'snacks' not in cols:
                            try:
                                engine.execute("ALTER TABLE ticket ADD COLUMN snacks INTEGER DEFAULT 0")
                            except Exception:
                                pass
                        if 'promo_type' not in cols:
                            try:
                                engine.execute("ALTER TABLE ticket ADD COLUMN promo_type VARCHAR(100)")
                            except Exception:
                                pass
                        if 'snacks_list' not in cols:
                            try:
                                engine.execute("ALTER TABLE ticket ADD COLUMN snacks_list VARCHAR(300)")
                            except Exception:
                                pass
                        if 'snacks_total' not in cols:
                            try:
                                engine.execute("ALTER TABLE ticket ADD COLUMN snacks_total FLOAT DEFAULT 0.0")
                            except Exception:
                                pass
                        # asegurar columna status en attendance
                        try:
                            res_att = engine.execute("PRAGMA table_info('attendance')").fetchall()
                            att_cols = [r[1] for r in res_att]
                            if 'status' not in att_cols:
                                try:
                                    engine.execute("ALTER TABLE attendance ADD COLUMN status VARCHAR(30)")
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        if 'entry_time' not in cols:
                            try:
                                engine.execute("ALTER TABLE ticket ADD COLUMN entry_time DATETIME")
                            except Exception:
                                pass
                        # Asegurarse columnas is_admin, email y role en tabla user
                        try:
                            res = engine.execute("PRAGMA table_info('user')").fetchall()
                            user_cols = [r[1] for r in res]
                            if 'is_admin' not in user_cols:
                                try:
                                    engine.execute("ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0")
                                except Exception:
                                    pass
                            if 'email' not in user_cols:
                                try:
                                    engine.execute("ALTER TABLE user ADD COLUMN email VARCHAR(200)")
                                except Exception:
                                    pass
                            if 'role' not in user_cols:
                                try:
                                    engine.execute("ALTER TABLE user ADD COLUMN role VARCHAR(50) DEFAULT 'Staff'")
                                except Exception:
                                    pass
                        except Exception:
                            pass
            except Exception:
                pass
        # Ruta para el panel de administración/dashboard
        @app.route('/dashboard')
        def dashboard():
            try:
                return render_template('dashboard.html')
            except Exception:
                # Si no existe la plantilla, devolver mensaje simple
                return "Dashboard temporal: plantilla no encontrada", 500

        if show_logs:
            # enable werkzeug request logging
            import logging
            logging.basicConfig(level=logging.INFO)
            werkzeug_logger = logging.getLogger('werkzeug')
            werkzeug_logger.setLevel(logging.INFO)
            socketio.run(app, host=os.environ.get('HOST', '0.0.0.0'), debug=False, port=int(os.environ.get('PORT', 3000)))
        else:
            # Silenciar banner/advertencia redirigiendo stderr a devnull
            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stderr(devnull):
                    socketio.run(app, host=os.environ.get('HOST', '0.0.0.0'), debug=False, port=int(os.environ.get('PORT', 3000)))
