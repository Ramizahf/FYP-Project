from flask import current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import log_in_user, normalize_email
from db import execute_db, query_db
from views.web_shared import (
    ROLE_LABELS,
    get_registration_form_data,
    registration_full_name,
    validate_registration,
)


def login():
    """
    GET  -> Show the login form.
    POST -> Validate credentials, start session, redirect to dashboard.
    """
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None

    if request.method == 'POST':
        email = normalize_email(request.form.get('email', ''))
        password = request.form.get('password', '').strip()

        if not email:
            error = 'Please enter your email address.'
        elif not password:
            error = 'Please enter your password.'
        else:
            user = query_db(
                "SELECT * FROM users WHERE email = ?",
                (email,), one=True
            )

            if user and check_password_hash(user['password_hash'], password):
                log_in_user(user)
                flash(
                    f"Welcome back, {user['full_name']}! "
                    f"Logged in as {ROLE_LABELS.get(user['role'], user['role'])}.",
                    'success'
                )
                return redirect(url_for('dashboard'))

            error = 'Incorrect email or password. Please try again.'

    return render_template('login.html', error=error)


def register():
    """
    GET  -> Show the registration form.
    POST -> Validate, create account, redirect to login.
    """
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    form_data = {}

    if request.method == 'POST':
        role = request.form.get('role', 'worker').strip()
        email = normalize_email(request.form.get('email', ''))
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        form_data = get_registration_form_data(role, email)
        full_name = registration_full_name(form_data)
        error = validate_registration(form_data, password, confirm)

        if not error:
            existing = query_db(
                "SELECT id FROM users WHERE email = ?",
                (email,), one=True
            )
            if existing:
                error = 'That email is already registered. Please log in instead.'
            else:
                pw_hash = generate_password_hash(password)
                worker_country = form_data['country'] if role == 'worker' else None
                worker_phone = form_data['phone'] if role == 'worker' else None

                new_user_id = execute_db(
                    "INSERT INTO users (full_name, email, password_hash, role, country, phone) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (full_name, email, pw_hash, role, worker_country, worker_phone)
                )

                if role == 'agent':
                    execute_db(
                        "INSERT INTO agents "
                        "  (user_id, agency_name, license_number, state, email) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            new_user_id,
                            full_name,
                            form_data['reg_num'],
                            form_data['agent_state'],
                            email,
                        )
                    )

                flash(
                    f'Account created! Welcome, {full_name}. '
                    f'Please log in with your email and password.',
                    'success'
                )
                return redirect(url_for('login'))

    return render_template('register.html', error=error, form_data=form_data)


def logout():
    """Clear the session and go home."""
    session.clear()
    response = redirect(url_for('index'))
    response.delete_cookie(
        current_app.config.get('SESSION_COOKIE_NAME', 'session'),
        path=current_app.config.get('SESSION_COOKIE_PATH', '/'),
        domain=current_app.config.get('SESSION_COOKIE_DOMAIN'),
        secure=current_app.config.get('SESSION_COOKIE_SECURE', False),
        httponly=current_app.config.get('SESSION_COOKIE_HTTPONLY', True),
        samesite=current_app.config.get('SESSION_COOKIE_SAMESITE'),
    )
    return response
