import secrets
from functools import wraps

from flask import flash, redirect, session, url_for
from werkzeug.security import generate_password_hash


def login_required(f):
    """Redirect to login if the user is not logged in."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access that page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    """Redirect if the logged-in user does not have the required role."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('You do not have permission to view that page.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated
    return decorator


def normalize_email(email):
    """Normalize user emails so auth lookups stay consistent."""
    normalized = (email or '').strip().lower()
    local_part, separator, domain = normalized.partition('@')
    if separator and domain == 'googlemail.com':
        domain = 'gmail.com'
    return f'{local_part}@{domain}' if separator else normalized


def is_verified_gmail_address(email):
    """Allow only Gmail addresses for Google OAuth sign-in."""
    return normalize_email(email).endswith('@gmail.com')


def create_unusable_password_hash():
    """Store a random hash for Google-created accounts without a local password."""
    return generate_password_hash(secrets.token_urlsafe(32))


def log_in_user(user):
    """Populate the Flask session for the authenticated user."""
    session.clear()
    session.permanent = True
    session['user_id'] = user['id']
    session['name'] = user['full_name']
    session['email'] = user['email']
    session['role'] = user['role']


def inject_user():
    """Inject current user info into all templates."""
    return {
        'current_user': {
            'id': session.get('user_id'),
            'name': session.get('name'),
            'email': session.get('email'),
            'role': session.get('role'),
            'is_auth': 'user_id' in session,
        }
    }


def init_auth(app):
    """Register shared template context."""
    app.context_processor(inject_user)
