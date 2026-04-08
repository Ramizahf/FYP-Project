from functools import wraps

from flask import flash, redirect, session, url_for


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
