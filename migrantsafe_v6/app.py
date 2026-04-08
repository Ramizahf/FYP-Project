"""
app.py
──────
MigrantSafe — Main Flask Application

This is the heart of the web app. It handles:
  • Database connections
  • All URL routes (pages)
  • Login / logout / register logic
  • Role-based access (worker, agent, admin)
  • Agents listing with search
  • Report submission
  • Chatbot API endpoint
  • Admin actions (verify / flag agents, resolve reports)

Run with:
    python app.py
"""

import os
import sqlite3
import json
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

from config import Config

# ─────────────────────────────────────────────────────────────
#  App Setup
# ─────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config.from_object(Config)


def ensure_database_schema():
    """
    Apply lightweight schema fixes for older SQLite databases.

    This keeps the app working even if database.db was created before
    worker profile fields like country/phone were added.
    """
    conn = sqlite3.connect(app.config['DATABASE'])
    try:
        cur = conn.cursor()
        existing_cols = {
            row[1] for row in cur.execute("PRAGMA table_info(users)").fetchall()
        }

        if 'country' not in existing_cols:
            cur.execute("ALTER TABLE users ADD COLUMN country TEXT")
        if 'phone' not in existing_cols:
            cur.execute("ALTER TABLE users ADD COLUMN phone TEXT")

        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────
#  Database Helpers
#  We use Flask's 'g' object to store one DB connection per
#  request, so we don't open a new connection on every query.
# ─────────────────────────────────────────────────────────────

def get_db():
    """Return the database connection for this request."""
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        # Return rows as dict-like objects (row['column_name'] works)
        g.db.row_factory = sqlite3.Row
    return g.db


def row_to_dict(row):
    """Convert a single sqlite3.Row to a plain Python dict."""
    return dict(row) if row else None


def rows_to_dicts(rows):
    """
    Convert a list of sqlite3.Row objects to a list of plain dicts.

    WHY THIS IS NEEDED:
    sqlite3.Row objects support row['column'] access but they are NOT
    JSON-serializable. Jinja2's {{ value | tojson }} filter needs plain
    Python dicts/lists. We convert every query result before passing it
    to render_template() so tojson always works correctly.
    """
    return [dict(r) for r in rows] if rows else []


@app.teardown_appcontext
def close_db(error):
    """Automatically close the DB connection when the request ends."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def query_db(sql, args=(), one=False):
    """
    Run a SELECT query and return results.
    one=True  → return a single row (or None)
    one=False → return a list of rows
    """
    cur = get_db().execute(sql, args)
    rv  = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


def execute_db(sql, args=()):
    """Run an INSERT / UPDATE / DELETE and commit."""
    db  = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


ensure_database_schema()


# ─────────────────────────────────────────────────────────────
#  Auth Decorators
#  These are reusable "guards" that you put on any route to
#  make sure only logged-in users (or specific roles) can visit.
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
#  Context Processor
#  Makes session data available in every template automatically.
# ─────────────────────────────────────────────────────────────

@app.context_processor
def inject_user():
    """Inject current user info into all templates."""
    return {
        'current_user': {
            'id':       session.get('user_id'),
            'name':     session.get('name'),
            'email':    session.get('email'),
            'role':     session.get('role'),
            'is_auth':  'user_id' in session,
        }
    }


# ─────────────────────────────────────────────────────────────
#  PUBLIC ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Landing page — public, no login required."""
    return render_template('index.html')


@app.route('/agents')
def agents():
    """
    Public agents directory.
    Supports search (q=) and status filter (status=verified|pending|reported).
    """
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()

    # Build query dynamically based on filters
    sql    = "SELECT * FROM agents WHERE 1=1"
    params = []

    if q:
        sql    += " AND (agency_name LIKE ? OR state LIKE ? OR industry LIKE ?)"
        like    = f"%{q}%"
        params += [like, like, like]

    if status in ('verified', 'pending', 'reported'):
        sql    += " AND verification_status = ?"
        params.append(status)

    sql += " ORDER BY verification_status ASC, agency_name ASC"

    all_agents = rows_to_dicts(query_db(sql, params))

    # Stats for the page header
    all_for_stats = query_db("SELECT verification_status FROM agents")
    stats = {
        'total':    len(all_for_stats),
        'verified': sum(1 for a in all_for_stats if a['verification_status'] == 'verified'),
        'pending':  sum(1 for a in all_for_stats if a['verification_status'] == 'pending'),
        'reported': sum(1 for a in all_for_stats if a['verification_status'] == 'reported'),
    }

    return render_template('agents.html',
                           agents=all_agents,
                           stats=stats,
                           q=q,
                           status_filter=status)


@app.route('/chatbot')
def chatbot():
    """Chatbot page — public."""
    return render_template('chatbot.html')


# ─────────────────────────────────────────────────────────────
#  AUTHENTICATION ROUTES
# ─────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    GET  → Show the login form.
    POST → Validate credentials, start session, redirect to dashboard.

    NOTE: We look up users by email ONLY (no role needed).
    The role is stored in the database — the user doesn't need to
    tell us what role they are; we read it automatically.
    """
    # Already logged in → go straight to dashboard
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None

    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        if not email:
            error = 'Please enter your email address.'
        elif not password:
            error = 'Please enter your password.'
        else:
            # Look up by email only — role is NOT required from the user
            user = query_db(
                "SELECT * FROM users WHERE email = ?",
                (email,), one=True
            )

            if user and check_password_hash(user['password_hash'], password):
                # ✅ Correct — store the session
                session.clear()
                session.permanent = True          # enables 2-hour timeout from config
                session['user_id'] = user['id']
                session['name']    = user['full_name']
                session['email']   = user['email']
                session['role']    = user['role']

                role_labels = {
                    'worker': 'Migrant Worker',
                    'agent':  'Recruitment Agent',
                    'admin':  'Administrator'
                }
                flash(
                    f"Welcome back, {user['full_name']}! "
                    f"Logged in as {role_labels.get(user['role'], user['role'])}.",
                    'success'
                )
                return redirect(url_for('dashboard'))
            else:
                error = 'Incorrect email or password. Please try again.'

    return render_template('login.html', error=error)


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    GET  → Show the registration form.
    POST → Validate, create account, redirect to login with a success message.

    Rules:
    - Email must be unique across the whole users table.
    - Workers fill in first name + last name.
    - Agents fill in agency name + JTK number + state.
    - Password must be at least 8 characters and match the confirmation.
    - On success → redirect to /login (never auto-login after register).
    - On error   → re-render the form with the error message.
    """
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error     = None
    form_data = {}   # keep form values so the user doesn't retype everything

    if request.method == 'POST':
        role     = request.form.get('role', 'worker').strip()
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm  = request.form.get('confirm_password', '').strip()

        # Save submitted values so we can repopulate the form on error
        form_data = {
            'role':         role,
            'email':        email,
            'first_name':   request.form.get('first_name', '').strip(),
            'last_name':    request.form.get('last_name',  '').strip(),
            'country':      request.form.get('country', '').strip(),
            'phone':        request.form.get('phone', '').strip(),
            'agency_name':  request.form.get('agency_name', '').strip(),
            'reg_num':      request.form.get('reg_num', '').strip(),
            'agent_state':  request.form.get('agent_state', '').strip(),
        }

        # Build display name from role-specific fields
        if role == 'worker':
            full_name = f"{form_data['first_name']} {form_data['last_name']}".strip()
        else:
            full_name = form_data['agency_name']

        # ── Validate ────────────────────────────────────────
        if role not in ('worker', 'agent'):
            error = 'Please select Worker or Agent.'
        elif not full_name:
            error = 'Please enter your full name.' if role == 'worker' else 'Please enter your agency name.'
        elif not email or '@' not in email or '.' not in email:
            error = 'Please enter a valid email address.'
        elif len(password) < 8:
            error = 'Password must be at least 8 characters.'
        elif not any(c.isupper() for c in password):
            error = 'Password must contain at least one uppercase letter (e.g. A, B, C).'
        elif not any(c.isdigit() for c in password):
            error = 'Password must contain at least one number (e.g. 1, 2, 3).'
        elif password != confirm:
            error = 'Passwords do not match.'
        elif role == 'agent' and not form_data['reg_num']:
            error = 'Please enter your JTK registration number.'
        elif role == 'agent' and not form_data['agent_state']:
            error = 'Please select your state / location.'
        else:
            # Check for duplicate email
            existing = query_db(
                "SELECT id FROM users WHERE email = ?", (email,), one=True
            )
            if existing:
                error = 'That email is already registered. Please log in instead.'
            else:
                # ✅ Create the user account
                # Workers: save country and phone; agents: these fields are N/A
                pw_hash = generate_password_hash(password)
                worker_country = form_data['country'] if role == 'worker' else None
                worker_phone   = form_data['phone']   if role == 'worker' else None
                new_user_id = execute_db(
                    "INSERT INTO users (full_name, email, password_hash, role, country, phone) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (full_name, email, pw_hash, role, worker_country, worker_phone)
                )

                # Agents also need a row in the agents table
                if role == 'agent':
                    execute_db(
                        "INSERT INTO agents "
                        "  (user_id, agency_name, license_number, state, email) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (new_user_id,
                         full_name,
                         form_data['reg_num'],
                         form_data['agent_state'],
                         email)
                    )

                flash(
                    f'Account created! Welcome, {full_name}. '
                    f'Please log in with your email and password.',
                    'success'
                )
                return redirect(url_for('login'))

    return render_template('register.html', error=error, form_data=form_data)


@app.route('/logout')
def logout():
    """Clear the session and go home."""
    name = session.get('name', '')
    session.clear()
    flash(f'You have been logged out{", " + name if name else ""}. See you next time!', 'info')
    return redirect(url_for('index'))


# ─────────────────────────────────────────────────────────────
#  AGENT DETAIL PAGE  (public — /agents/<id>)
# ─────────────────────────────────────────────────────────────

@app.route('/agents/<int:agent_id>')
def agent_detail(agent_id):
    """
    Public profile page for a single agent.
    Shows full details + report count + report button.
    """
    agent = row_to_dict(query_db(
        "SELECT * FROM agents WHERE id = ?", (agent_id,), one=True
    ))
    if not agent:
        flash('Agent not found.', 'danger')
        return redirect(url_for('agents'))

    # Count reports filed against this agent
    report_count = query_db(
        "SELECT COUNT(*) as c FROM reports WHERE agent_id = ? AND status = 'open'",
        (agent_id,), one=True
    )['c']

    return render_template('agent_detail.html',
                           agent=agent,
                           report_count=report_count)


# ─────────────────────────────────────────────────────────────
#  WORKER: VIEW MY REPORTS  (/my-reports)
# ─────────────────────────────────────────────────────────────

@app.route('/my-reports')
@role_required('worker')
def my_reports():
    """Worker can see all reports they have submitted and their current status."""
    reports = rows_to_dicts(query_db(
        "SELECT * FROM reports WHERE worker_id = ? ORDER BY created_at DESC",
        (session['user_id'],)
    ))
    return render_template('my_reports.html', reports=reports)


# ─────────────────────────────────────────────────────────────
#  MIGRATION GUIDE  (/guide)
# ─────────────────────────────────────────────────────────────

@app.route('/guide')
def migration_guide():
    """
    Step-by-step migration process guide.
    Public page — no login required.
    Available in English, Malay, and Bangla via JS lang switcher.
    """
    return render_template('guide.html')


# ─────────────────────────────────────────────────────────────
#  DASHBOARD — Role-based redirect
# ─────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    """Send the user to whichever dashboard matches their role."""
    role = session.get('role')
    if role == 'worker':
        return redirect(url_for('dashboard_worker'))
    elif role == 'agent':
        return redirect(url_for('dashboard_agent'))
    elif role == 'admin':
        return redirect(url_for('dashboard_admin'))
    # Unknown role — log them out cleanly
    session.clear()
    flash('Your account role is not recognised. Please contact support.', 'danger')
    return redirect(url_for('login'))


# ─────────────────────────────────────────────────────────────
#  WORKER DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.route('/dashboard/worker')
@role_required('worker')
def dashboard_worker():
    """Worker's personal dashboard."""
    user_id = session['user_id']

    # Count how many reports this worker has filed
    my_reports = query_db(
        "SELECT COUNT(*) as cnt FROM reports WHERE worker_id = ?",
        (user_id,), one=True
    )
    report_count = my_reports['cnt'] if my_reports else 0

    # Platform stats shown on the worker dashboard
    stats = {
        'verified': query_db("SELECT COUNT(*) as c FROM agents WHERE verification_status='verified'", one=True)['c'],
        'reported': query_db("SELECT COUNT(*) as c FROM agents WHERE verification_status='reported'", one=True)['c'],
    }

    # Recent agents (for the quick preview list)
    recent_agents = rows_to_dicts(query_db(
        "SELECT * FROM agents ORDER BY id DESC LIMIT 4"
    ))

    # Worker's own profile details (country + phone saved at registration)
    worker_profile = row_to_dict(query_db(
        "SELECT country, phone FROM users WHERE id = ?", (user_id,), one=True
    ))

    return render_template('dashboard-worker.html',
                           report_count=report_count,
                           stats=stats,
                           recent_agents=recent_agents,
                           worker_profile=worker_profile)


# ─────────────────────────────────────────────────────────────
#  AGENT DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.route('/dashboard/agent')
@role_required('agent')
def dashboard_agent():
    """Recruitment agent's dashboard."""
    user_id = session['user_id']

    agent = row_to_dict(query_db(
        "SELECT * FROM agents WHERE user_id = ?",
        (user_id,), one=True
    ))

    # Reports filed against this agent (show all statuses so agent can see history)
    reports = []
    if agent:
        reports = rows_to_dicts(query_db(
            "SELECT * FROM reports WHERE agent_id = ? ORDER BY created_at DESC",
            (agent['id'],)
        ))

    # Count open reports against this agent from real data
    open_report_count = sum(1 for r in reports if r['status'] == 'open')

    # Profile views: placeholder 0 until real tracking is implemented.
    # Future: query a profile_views table filtered by agent_id and this month.
    # Suggested future schema:
    #   CREATE TABLE profile_views (
    #       id             INTEGER PRIMARY KEY AUTOINCREMENT,
    #       agent_id       INTEGER NOT NULL REFERENCES agents(id),
    #       viewer_user_id INTEGER REFERENCES users(id),  -- NULL if not logged in
    #       viewed_at      TEXT NOT NULL DEFAULT (datetime('now'))
    #   );
    profile_views = 0

    # Average rating: not yet implemented — pass None so template shows N/A
    average_rating = None

    return render_template('dashboard-agent.html',
                           agent=agent,
                           reports=reports,
                           open_report_count=open_report_count,
                           profile_views=profile_views,
                           average_rating=average_rating)


# ─────────────────────────────────────────────────────────────
#  ADMIN DASHBOARD
# ─────────────────────────────────────────────────────────────

@app.route('/dashboard/admin')
@role_required('admin')
def dashboard_admin():
    """Admin's management dashboard."""
    all_agents  = rows_to_dicts(query_db("SELECT * FROM agents ORDER BY verification_status, agency_name"))
    open_reports = rows_to_dicts(query_db(
        "SELECT r.*, a.agency_name FROM reports r LEFT JOIN agents a ON r.agent_id = a.id WHERE r.status = 'open' ORDER BY r.created_at DESC"
    ))

    stats = {
        'total':    len(all_agents),
        'verified': sum(1 for a in all_agents if a['verification_status'] == 'verified'),
        'pending':  sum(1 for a in all_agents if a['verification_status'] == 'pending'),
        'reported': sum(1 for a in all_agents if a['verification_status'] == 'reported'),
        'open_reports': len(open_reports),
    }

    return render_template('dashboard-admin.html',
                           agents=all_agents,
                           open_reports=open_reports,
                           stats=stats)


# ─────────────────────────────────────────────────────────────
#  ADMIN ACTIONS
# ─────────────────────────────────────────────────────────────

@app.route('/admin/agent/<int:agent_id>/status', methods=['POST'])
@role_required('admin')
def update_agent_status(agent_id):
    """Admin sets an agent's verification status."""
    new_status = request.form.get('status')
    if new_status not in ('verified', 'pending', 'reported'):
        flash('Invalid status value.', 'danger')
        return redirect(url_for('dashboard_admin'))
    execute_db(
        "UPDATE agents SET verification_status = ? WHERE id = ?",
        (new_status, agent_id)
    )
    flash(f'Agent status updated to {new_status}.', 'success')
    return redirect(url_for('dashboard_admin'))


@app.route('/admin/agent/<int:agent_id>/delete', methods=['POST'])
@role_required('admin')
def delete_agent(agent_id):
    """Admin permanently removes an agent record and all associated reports."""
    agent = row_to_dict(query_db("SELECT * FROM agents WHERE id = ?", (agent_id,), one=True))
    if not agent:
        flash('Agent not found.', 'danger')
        return redirect(url_for('dashboard_admin'))
    execute_db("DELETE FROM reports WHERE agent_id = ?", (agent_id,))
    execute_db("DELETE FROM agents WHERE id = ?", (agent_id,))
    flash(f'Agent "{agent["agency_name"]}" has been removed from the platform.', 'success')
    return redirect(url_for('dashboard_admin'))


@app.route('/admin/users')
@role_required('admin')
def admin_users():
    """Admin views all registered user accounts."""
    users = rows_to_dicts(query_db(
        "SELECT id, full_name, email, role, created_at FROM users ORDER BY role, created_at DESC"
    ))
    # Count reports per worker for context
    report_counts = {}
    for r in query_db("SELECT worker_id, COUNT(*) as c FROM reports GROUP BY worker_id"):
        report_counts[r['worker_id']] = r['c']
    return render_template('admin_users.html', users=users, report_counts=report_counts)


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@role_required('admin')
def admin_delete_user(user_id):
    """Admin removes a user account. Cannot delete own account."""
    if user_id == session['user_id']:
        flash('You cannot delete your own admin account.', 'danger')
        return redirect(url_for('admin_users'))
    user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_users'))
    name = user['full_name']
    # Cascade delete linked data
    execute_db("DELETE FROM agents WHERE user_id = ?", (user_id,))
    execute_db("DELETE FROM reports WHERE worker_id = ?", (user_id,))
    execute_db("DELETE FROM chatbot_logs WHERE user_id = ?", (user_id,))
    execute_db("DELETE FROM users WHERE id = ?", (user_id,))
    flash(f'User "{name}" has been permanently removed.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/report/<int:report_id>/resolve', methods=['POST'])
@role_required('admin')
def resolve_report(report_id):
    """
    Admin marks a report as resolved or dismissed.
    action=flag    → also flags the agent as 'reported'
    action=dismiss → just closes the report
    """
    action = request.form.get('action')

    if action == 'flag':
        # Get the report to find the agent
        report = row_to_dict(query_db("SELECT * FROM reports WHERE id = ?", (report_id,), one=True))
        if report and report['agent_id']:
            execute_db(
                "UPDATE agents SET verification_status = 'reported' WHERE id = ?",
                (report['agent_id'],)
            )
        execute_db("UPDATE reports SET status = 'resolved' WHERE id = ?", (report_id,))
        flash('Report resolved. Agent has been flagged.', 'success')

    elif action == 'dismiss':
        execute_db("UPDATE reports SET status = 'dismissed' WHERE id = ?", (report_id,))
        flash('Report dismissed.', 'info')

    return redirect(url_for('dashboard_admin'))


# ─────────────────────────────────────────────────────────────
#  REPORT SUBMISSION (Workers)
# ─────────────────────────────────────────────────────────────

@app.route('/report', methods=['GET', 'POST'])
def submit_report():
    """
    Worker-only report submission.
    GET  → Show report form (with optional agent_id pre-filled).
    POST → Validate and save report to database.
    Only authenticated users with role='worker' may access this route.
    """
    # Auth + role check with specific flash messages
    if 'user_id' not in session:
        flash('Please log in to submit a report.', 'warning')
        return redirect(url_for('login'))
    if session.get('role') != 'worker':
        flash('Only workers can submit reports.', 'warning')
        return redirect(url_for('dashboard'))
    agent_id_param = request.args.get('agent_id')
    agent = None
    if agent_id_param:
        agent = row_to_dict(query_db("SELECT * FROM agents WHERE id = ?", (agent_id_param,), one=True))

    if request.method == 'POST':
        agent_name    = request.form.get('agent_name', '').strip()
        agent_id      = request.form.get('agent_id') or None
        report_reason = request.form.get('report_reason', '').strip()
        description   = request.form.get('description', '').strip()
        incident_date = request.form.get('incident_date', '').strip() or None

        # ── Validation ───────────────────────────────────────
        errors = []
        if not agent_name:
            errors.append('Please enter the agent or agency name.')
        elif len(agent_name) < 3:
            errors.append('Agent name must be at least 3 characters.')
        elif len(agent_name) > 200:
            errors.append('Agent name is too long (max 200 characters).')

        if not report_reason:
            errors.append('Please select the type of issue.')

        if not description:
            errors.append('Please describe what happened.')
        elif len(description) < 20:
            errors.append('Please provide more detail (at least 20 characters).')
        elif len(description) > 2000:
            errors.append('Description is too long (max 2000 characters).')

        if errors:
            for e in errors:
                flash(e, 'danger')
        else:
            execute_db("""
                INSERT INTO reports
                    (worker_id, agent_id, agent_name, report_reason, description, incident_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session['user_id'], agent_id, agent_name, report_reason, description, incident_date))
            flash('Your report has been submitted. Our admin team will review it within 48 hours.', 'success')
            return redirect(url_for('my_reports'))

    all_agents = rows_to_dicts(query_db("SELECT * FROM agents ORDER BY agency_name"))
    return render_template('report.html', agent=agent, all_agents=all_agents)


# ─────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────
#  WORKER PROFILE UPDATE (Workers only)
# ─────────────────────────────────────────────────────────────

@app.route('/worker/profile', methods=['POST'])
@role_required('worker')
def update_worker_profile():
    """Allow a logged-in worker to update their country and phone number."""
    user_id = session['user_id']

    country = request.form.get('country', '').strip()
    phone   = request.form.get('phone',   '').strip()

    # Validate phone length if provided
    if phone and len(phone) > 20:
        flash('Phone number is too long (max 20 characters).', 'danger')
        return redirect(url_for('dashboard_worker'))

    # Only update fields the worker is allowed to change
    execute_db(
        "UPDATE users SET country = ?, phone = ? WHERE id = ?",
        (country or None, phone or None, user_id)
    )

    flash('Profile updated successfully.', 'success')
    return redirect(url_for('dashboard_worker'))


# ─────────────────────────────────────────────────────────────
#  AGENT PROFILE UPDATE (Agents only)
# ─────────────────────────────────────────────────────────────

@app.route('/agent/profile', methods=['POST'])
@role_required('agent')
def update_agent_profile():
    """Save changes to an agent's own profile."""
    user_id = session['user_id']
    agent   = row_to_dict(query_db("SELECT * FROM agents WHERE user_id = ?", (user_id,), one=True))

    agency_name    = request.form.get('agency_name', '').strip()
    license_number = request.form.get('license_number', '').strip()
    state          = request.form.get('state', '').strip()
    industry       = request.form.get('industry', '').strip()
    phone          = request.form.get('phone', '').strip()
    description    = request.form.get('description', '').strip()

    # ── Validation ──────────────────────────────────────────
    errors = []
    if not agency_name:
        errors.append('Agency name is required.')
    elif len(agency_name) < 3:
        errors.append('Agency name must be at least 3 characters.')
    elif len(agency_name) > 200:
        errors.append('Agency name is too long (max 200 characters).')

    if not license_number:
        errors.append('JTK registration number is required.')
    elif len(license_number) > 100:
        errors.append('License number is too long.')

    if not state:
        errors.append('Please select your state.')

    if phone and len(phone) > 20:
        errors.append('Phone number is too long.')

    if description and len(description) > 1000:
        errors.append('Description is too long (max 1000 characters).')

    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('dashboard_agent'))

    if agent:
        # Update existing record
        execute_db("""
            UPDATE agents
            SET agency_name = ?, license_number = ?, state = ?,
                industry = ?, phone = ?, description = ?
            WHERE user_id = ?
        """, (agency_name, license_number, state, industry, phone, description, user_id))
    else:
        # Create a new record if one doesn't exist yet
        execute_db("""
            INSERT INTO agents (user_id, agency_name, license_number, state, industry, phone, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, agency_name, license_number, state, industry, phone, session.get('email', '')))

    # Update the session name to reflect agency name
    session['name'] = agency_name
    flash('Profile saved! Admins will be notified to review your details.', 'success')
    return redirect(url_for('dashboard_agent'))


# ─────────────────────────────────────────────────────────────
#  CHATBOT API ENDPOINT
# ─────────────────────────────────────────────────────────────

# ── MigrantSafe chatbot system prompts (one per language) ─────
CHATBOT_SYSTEM = {
    'en': """You are MigrantSafe Assistant — a helpful, warm, and knowledgeable guide for migrant workers in Malaysia.

Your role is to answer questions about:
- Recruitment agent verification (Verified / Pending / Reported status on MigrantSafe)
- Recruitment fees (employers MUST pay, NOT workers — zero-cost migration policy)
- Malaysian work documents: FOMEMA medical check, VP(TE) work permit visa, employment pass
- Step-by-step recruitment process: apply → quota → medical → visa → arrival → work
- Migrant worker rights under Malaysian law: right to keep passport, receive full salary on time, safe working hours, not be threatened
- How to report unethical agents using MigrantSafe's report form
- Common scams: excessive fees, fake job offers, document forgery, passport confiscation
- JTKSM (Department of Labour) hotline: 03-8000 8000

Rules:
- Be warm, clear and simple. Use short paragraphs. Many users have low literacy.
- Use bullet points and emojis sparingly to make information easier to read.
- If someone describes being in danger or exploited, always provide the JTKSM hotline (03-8000 8000).
- Never give legal or medical advice — always suggest consulting a professional.
- For unrelated questions, politely redirect to recruitment topics.
- ALWAYS respond in English only.""",

    'ms': """Anda adalah MigrantSafe Assistant — panduan yang membantu dan berpengetahuan untuk pekerja asing di Malaysia.

Peranan anda adalah menjawab soalan tentang:
- Pengesahan ejen pengambilan (status Disahkan / Belum Disahkan / Dilaporkan di MigrantSafe)
- Yuran pengambilan (MAJIKAN mesti bayar, BUKAN pekerja — dasar migrasi tanpa kos)
- Dokumen kerja Malaysia: pemeriksaan perubatan FOMEMA, visa permit kerja VP(TE), pas pekerjaan
- Proses pengambilan langkah demi langkah: mohon → kuota → perubatan → visa → tiba → kerja
- Hak pekerja asing di bawah undang-undang Malaysia: hak menyimpan pasport, menerima gaji penuh tepat masa, waktu kerja selamat
- Cara melaporkan ejen tidak beretika menggunakan borang laporan MigrantSafe
- Penipuan biasa: yuran berlebihan, tawaran kerja palsu, pemalsuan dokumen, rampasan pasport
- Talian hotline JTKSM: 03-8000 8000

Peraturan:
- Gunakan bahasa mudah dan ringkas.
- Jika seseorang dalam bahaya atau dieksploitasi, berikan hotline JTKSM (03-8000 8000).
- Jangan berikan nasihat perundangan atau perubatan.
- WAJIB menjawab dalam Bahasa Melayu sahaja tanpa pengecualian.""",

    'bn': """আপনি MigrantSafe Assistant — মালয়েশিয়ায় অভিবাসী শ্রমিকদের জন্য একজন সহায়ক ও জ্ঞানসম্পন্ন গাইড।

আপনার ভূমিকা হল নিম্নলিখিত বিষয়ে প্রশ্নের উত্তর দেওয়া:
- রিক্রুটমেন্ট এজেন্ট যাচাইকরণ (MigrantSafe-এ যাচাইকৃত / অপেক্ষমান / রিপোর্টকৃত স্ট্যাটাস)
- রিক্রুটমেন্ট ফি (নিয়োগকর্তাকে দিতে হবে, কর্মীকে নয় — জিরো-কস্ট মাইগ্রেশন নীতি)
- মালয়েশিয়ার কাজের ডকুমেন্ট: FOMEMA মেডিকেল চেক, VP(TE) ওয়ার্ক পারমিট ভিসা, এমপ্লয়মেন্ট পাস
- ধাপে ধাপে নিয়োগ প্রক্রিয়া: আবেদন → কোটা → মেডিকেল → ভিসা → আগমন → কাজ
- মালয়েশিয়ার আইনের অধীনে অভিবাসী শ্রমিকদের অধিকার: পাসপোর্ট রাখার অধিকার, সময়মতো পূর্ণ বেতন, নিরাপদ কর্মঘণ্টা
- MigrantSafe-এর রিপোর্ট ফর্ম ব্যবহার করে অনৈতিক এজেন্ট রিপোর্ট করার পদ্ধতি
- সাধারণ প্রতারণা: অতিরিক্ত ফি, ভুয়া চাকরির অফার, ডকুমেন্ট জালিয়াতি, পাসপোর্ট বাজেয়াপ্ত
- JTKSM হটলাইন: ০৩-৮০০০ ৮০০০

নিয়মাবলী:
- সহজ এবং সংক্ষিপ্ত ভাষা ব্যবহার করুন।
- কেউ বিপদে থাকলে JTKSM হটলাইন (০৩-৮০০০ ৮০০০) দিন।
- আইনি বা চিকিৎসা পরামর্শ দেবেন না।
- অবশ্যই শুধুমাত্র বাংলায় উত্তর দিন।"""
}


@app.route('/api/chat', methods=['POST'])
def chat_api():
    """
    Accepts: { "message": "...", "language": "en|ms|bn", "history": [...] }
    Returns: { "response": "..." }
    Logs every exchange to chatbot_logs table.
    """
    data     = request.get_json(silent=True) or {}
    message  = data.get('message', '').strip()
    language = data.get('language', 'en')
    history  = data.get('history', [])   # previous turns for context

    if not message:
        return jsonify({'response': 'Please type a message.'}), 400

    reply = get_bot_reply(message, language, history)

    # Log to DB
    user_id = session.get('user_id')
    try:
        execute_db(
            "INSERT INTO chatbot_logs (user_id, message, response, language) VALUES (?, ?, ?, ?)",
            (user_id, message[:1000], reply[:2000], language)
        )
    except Exception:
        pass

    return jsonify({'response': reply})


def get_bot_reply(message: str, language: str = 'en', history: list = None) -> str:
    """
    Calls the Google Gemini API (FREE tier — no credit card needed).

    To enable real AI responses:
      1. Go to https://aistudio.google.com/app/apikey
      2. Sign in with your Google account and click 'Create API Key'
      3. Copy the key and paste it into your .env file:
             GEMINI_API_KEY=your-key-here
      4. Restart the app: python app.py

    Falls back to the offline FAQ if no key is set or if the API is unavailable.
    The free tier allows ~1,500 requests/day which is more than enough for a FYP.
    """
    import urllib.request
    import urllib.error

    api_key = os.environ.get('OPENCODE_API_KEY', '').strip()
    base_url = os.environ.get(
        'OPENCODE_API_BASE_URL',
        'https://openrouter.ai/api/v1'
    ).strip().rstrip('/')
    model = os.environ.get(
        'OPENCODE_MODEL',
        'google/gemma-4-31b-it:free'
    ).strip()

    # ── Real AI path (Google Gemini — free tier) ─────────────
    if api_key:
        system_prompt = CHATBOT_SYSTEM.get(language, CHATBOT_SYSTEM['en'])

        # Build the conversation contents array
        # Gemini uses 'user' and 'model' roles (not 'assistant')
        messages = [{'role': 'system', 'content': system_prompt}]

        # Inject system instructions as the first user turn
        # (Gemini Flash supports a system_instruction field directly)
        if history:
            for turn in history[-6:]:
                role    = turn.get('role', '')
                content = turn.get('content', '')
                if role in ('user', 'assistant') and content:
                    messages.append({'role': role, 'content': content})

        messages.append({'role': 'user', 'content': message})

        payload = json.dumps({
            'model': model,
            'messages': messages,
            'temperature': 0.7,
            'max_tokens': 600
        }).encode()

        # Using gemini-1.5-flash — fast, free, and capable
        url = f'{base_url}/chat/completions'

        req = urllib.request.Request(
            url,
            data    = payload,
            method  = 'POST',
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
                'HTTP-Referer': 'http://localhost',
                'X-Title': 'MigrantSafe Chatbot'
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                choices = data.get('choices') or []
                if choices:
                    content = choices[0].get('message', {}).get('content', '').strip()
                    if content:
                        return content
        except Exception as e:
            app.logger.warning(f"Chat API error: {e}")
            # Fall through to offline responses below

    # ── Offline FAQ fallback (used when no API key is set) ───
    return _offline_reply(message, language)


def _offline_reply(message: str, language: str) -> str:
    """
    Smart FAQ fallback using a scoring system for broad natural-language matching.

    Each topic has a PRIMARY keyword list (high-weight) and SECONDARY list (low-weight).
    The message is scored against all topics and the highest-scoring one wins.
    This means conversational phrases like "the agent lied to me", "I need help",
    or "your answers are not correct" can still match meaningful topics.

    If nothing scores at all, a clarifying prompt is returned instead of a useless
    generic list — asking the user to try rephrasing with a concrete example.
    """
    low = message.lower()

    # ── TOPIC DEFINITIONS ─────────────────────────────────────────────────────
    # Each entry: (topic_id, primary_keywords[], secondary_keywords[], answers{})
    # Primary match = 2 points, secondary match = 1 point. Highest total wins.

    TOPICS = [
        {
            'id': 'fees',
            'primary': ['fee', 'fees', 'upfront', 'advance payment', 'paid too much',
                        'overcharge', 'excessive', 'rm 5000', 'rm 10000', 'money agent',
                        'cost recruitment', 'pay agent', 'deposit agent'],
            'secondary': ['pay', 'money', 'rm', 'ringgit', 'cost', 'charge', 'expensive',
                          'illegal', 'asked to pay', 'agent wants', 'agent asked'],
            'answers': {
                'en': "💰 RECRUITMENT FEES — Important Information\n\nRecruitment fees must be paid by your EMPLOYER, not by you. This is Malaysian law (zero-cost migration policy).\n\nIf an agent asks you to pay upfront fees:\n• This is likely ILLEGAL\n• Common amounts used to scam workers: RM 3,000–15,000\n• Many workers take loans to pay these fees and fall into debt\n\nWhat you should do:\n1. Do NOT pay the agent directly\n2. Report them on MigrantSafe using the Report feature\n3. Call JTKSM hotline: 03-8000 8000\n\nYou can also verify if an agent is licensed before trusting them — go to Find Agents on MigrantSafe.",
                'ms': "💰 YURAN PENGAMBILAN — Maklumat Penting\n\nYuran pengambilan mesti dibayar oleh MAJIKAN anda, bukan oleh anda. Ini adalah undang-undang Malaysia (dasar migrasi tanpa kos).\n\nJika ejen meminta anda membayar yuran pendahuluan:\n• Ini mungkin HARAM\n• Jumlah biasa yang digunakan untuk menipu pekerja: RM 3,000–15,000\n\nApa yang perlu anda lakukan:\n1. JANGAN bayar ejen secara terus\n2. Laporkan mereka di MigrantSafe\n3. Hubungi JTKSM: 03-8000 8000",
                'bn': "💰 রিক্রুটমেন্ট ফি — গুরুত্বপূর্ণ তথ্য\n\nরিক্রুটমেন্ট ফি আপনার নিয়োগকর্তাকে দিতে হবে, আপনাকে নয়। এটি মালয়েশিয়ার আইন (জিরো-কস্ট মাইগ্রেশন নীতি)।\n\nযদি এজেন্ট আপনাকে আগাম ফি দিতে বলে:\n• এটি সম্ভবত অবৈধ\n• সাধারণ প্রতারণার পরিমাণ: RM ৩,০০০–১৫,০০০\n\nআপনি যা করবেন:\n১. সরাসরি এজেন্টকে পয়সা দেবেন না\n২. MigrantSafe-এ রিপোর্ট করুন\n৩. JTKSM হটলাইন: ০৩-৮০০০ ৮০০০",
            }
        },
        {
            'id': 'verify_agent',
            'primary': ['verify agent', 'check agent', 'is agent real', 'is agent legit',
                        'agent fake', 'agent scam', 'agent trustworthy', 'agent license',
                        'licensed agent', 'registered agent', 'fake agent', 'real agent',
                        'agent correct', 'agent wrong', 'agent lying', 'agent lied',
                        'agent not correct', 'answers not correct', 'wrong answer',
                        'not accurate', 'incorrect', 'misleading'],
            'secondary': ['agent', 'verify', 'check', 'trust', 'legit', 'real', 'scam',
                          'fraud', 'fake', 'correct', 'accurate', 'wrong', 'lied', 'lie'],
            'answers': {
                'en': "🛡️ HOW TO VERIFY IF AN AGENT IS LEGITIMATE\n\nOn MigrantSafe, every registered agent has a clear status badge:\n\n✅ Verified — Admin-approved. The agent's license has been checked. Safer to use.\n⏳ Pending — Under review. Not yet confirmed. Proceed with caution.\n⚠️ Reported — Worker complaints filed. DO NOT engage with this agent.\n\nTo check an agent:\n1. Go to Find Agents on MigrantSafe\n2. Search the agent's name or company\n3. Check their status badge before paying anything\n\nYou can also check if an agent is officially registered with Malaysia's JTKSM (Department of Labour) by calling: 03-8000 8000\n\nNever trust an agent based only on social media or word of mouth.",
                'ms': "🛡️ CARA MENGESAHKAN SAMA ADA EJEN SAH\n\nDi MigrantSafe, setiap ejen berdaftar mempunyai lencana status yang jelas:\n\n✅ Disahkan — Diluluskan admin. Lesen ejen telah disemak.\n⏳ Belum Disahkan — Sedang disemak. Belum disahkan.\n⚠️ Dilaporkan — Aduan pekerja difailkan. JANGAN berurusan dengan ejen ini.\n\nUntuk menyemak ejen:\n1. Pergi ke Cari Ejen di MigrantSafe\n2. Cari nama ejen atau syarikat\n3. Semak lencana status mereka sebelum membayar apa-apa",
                'bn': "🛡️ এজেন্ট বৈধ কিনা যাচাই করার পদ্ধতি\n\nMigrantSafe-এ প্রতিটি নিবন্ধিত এজেন্টের একটি স্পষ্ট স্ট্যাটাস ব্যাজ আছে:\n\n✅ যাচাইকৃত — অ্যাডমিন অনুমোদিত। এজেন্টের লাইসেন্স যাচাই করা হয়েছে।\n⏳ অপেক্ষমান — পর্যালোচনাধীন। এখনো নিশ্চিত নয়।\n⚠️ রিপোর্টকৃত — শ্রমিকদের অভিযোগ দাখিল। এই এজেন্টের সাথে যোগাযোগ করবেন না।\n\nএজেন্ট যাচাই করতে:\n১. MigrantSafe-এ এজেন্ট খুঁজুন-এ যান\n২. এজেন্টের নাম বা কোম্পানি সার্চ করুন\n৩. কিছু পয়সা দেওয়ার আগে তাদের স্ট্যাটাস ব্যাজ দেখুন",
            }
        },
        {
            'id': 'visa_documents',
            'primary': ['visa', 'vp(te)', 'work permit', 'fomema', 'medical check',
                        'medical certificate', 'employment pass', 'work visa',
                        'how long visa', 'visa processing', 'permit processing'],
            'secondary': ['document', 'passport', 'medical', 'permit', 'certificate',
                          'paper', 'paperwork', 'weeks', 'processing', 'apply visa'],
            'answers': {
                'en': "📋 DOCUMENTS NEEDED TO WORK IN MALAYSIA\n\nTo work legally, you need all of these:\n1. Valid passport (with at least 18 months remaining)\n2. VP(TE) work permit visa — issued by Malaysian Immigration\n3. FOMEMA medical certificate — health screening done in Malaysia after arrival\n4. Signed employment contract — in a language you understand\n\nHow long does it take?\n• FOMEMA medical: usually within 1–3 days of arrival\n• VP(TE) visa processing: 2–6 weeks after FOMEMA is cleared\n• Total from arrival to legal work: approximately 3–7 weeks\n\n⚠️ Keep photocopies of ALL documents. Your employer cannot legally hold your originals.",
                'ms': "📋 DOKUMEN YANG DIPERLUKAN UNTUK BEKERJA DI MALAYSIA\n\nUntuk bekerja secara sah, anda memerlukan semua ini:\n1. Pasport yang sah (sekurang-kurangnya 18 bulan berbaki)\n2. Visa permit kerja VP(TE) — dikeluarkan oleh Imigresen Malaysia\n3. Sijil perubatan FOMEMA — pemeriksaan kesihatan di Malaysia selepas ketibaan\n4. Kontrak pekerjaan yang ditandatangani — dalam bahasa yang anda faham\n\nBerapa lama proses ini?\n• Perubatan FOMEMA: biasanya 1–3 hari selepas ketibaan\n• Pemprosesan visa VP(TE): 2–6 minggu selepas FOMEMA diluluskan",
                'bn': "📋 মালয়েশিয়ায় কাজ করতে প্রয়োজনীয় ডকুমেন্ট\n\nবৈধভাবে কাজ করতে আপনার প্রয়োজন:\n১. বৈধ পাসপোর্ট (কমপক্ষে ১৮ মাস মেয়াদ বাকি)\n২. VP(TE) ওয়ার্ক পারমিট ভিসা — মালয়েশিয়ার ইমিগ্রেশন কর্তৃক ইস্যুকৃত\n৩. FOMEMA মেডিকেল সার্টিফিকেট — মালয়েশিয়ায় আসার পর স্বাস্থ্য পরীক্ষা\n৪. স্বাক্ষরিত চাকরির চুক্তি — আপনি বুঝতে পারেন এমন ভাষায়\n\nকতদিন লাগে?\n• FOMEMA মেডিকেল: আগমনের ১–৩ দিনের মধ্যে\n• VP(TE) ভিসা প্রক্রিয়া: FOMEMA ক্লিয়ার হওয়ার পর ২–৬ সপ্তাহ",
            }
        },
        {
            'id': 'rights',
            'primary': ['my rights', 'worker rights', 'labour rights', 'what rights',
                        'rights malaysia', 'exploited', 'abused', 'harassed', 'threatened',
                        'maltreated', 'mistreated', 'unfair treatment', 'forced to work',
                        'overtime forced', 'no day off'],
            'secondary': ['right', 'rights', 'law', 'legal', 'protect', 'treatment',
                          'abuse', 'exploit', 'fair', 'unfair', 'entitle', 'allowed'],
            'answers': {
                'en': "⚖️ YOUR RIGHTS AS A MIGRANT WORKER IN MALAYSIA\n\nUnder Malaysian law, you have the right to:\n\n🪪 Keep your own passport — No employer or agent can legally hold it\n💵 Receive your FULL salary on time — Every month without illegal deductions\n⏰ Safe working hours — Maximum 8 hours/day, 48 hours/week\n🛡️ Not be threatened, abused, or harassed\n🏥 Access to medical care when sick\n📄 Receive a written employment contract before starting work\n🌍 Contact your home country's embassy at any time\n\nIf any of these rights are violated:\n• Call JTKSM (Labour Department): 03-8000 8000\n• Report the agent or employer on MigrantSafe\n• Contact your home country's embassy in KL",
                'ms': "⚖️ HAK ANDA SEBAGAI PEKERJA ASING DI MALAYSIA\n\nDi bawah undang-undang Malaysia, anda berhak untuk:\n\n🪪 Menyimpan pasport sendiri — Tiada majikan atau ejen boleh menahannya\n💵 Menerima gaji penuh tepat masa — Setiap bulan tanpa potongan haram\n⏰ Waktu kerja yang selamat — Maksimum 8 jam/hari, 48 jam/minggu\n🛡️ Tidak diancam, dianiaya, atau diganggu\n🏥 Akses kepada rawatan perubatan\n\nJika hak anda dilanggar: Hubungi JTKSM: 03-8000 8000",
                'bn': "⚖️ মালয়েশিয়ায় অভিবাসী শ্রমিক হিসেবে আপনার অধিকার\n\nমালয়েশিয়ার আইনের অধীনে আপনার অধিকার আছে:\n\n🪪 নিজের পাসপোর্ট রাখার — কোনো নিয়োগকর্তা বা এজেন্ট আইনত এটি ধরে রাখতে পারবে না\n💵 সময়মতো পূর্ণ বেতন পাওয়ার — প্রতি মাসে অবৈধ কাটাকাটি ছাড়া\n⏰ নিরাপদ কর্মঘণ্টা — সর্বোচ্চ ৮ ঘণ্টা/দিন, ৪৮ ঘণ্টা/সপ্তাহ\n🛡️ হুমকি, নির্যাতন বা হয়রানি না সহ্য করার\n🏥 অসুস্থ হলে চিকিৎসা পাওয়ার\n\nঅধিকার লঙ্ঘিত হলে: JTKSM: ০৩-৮০০০ ৮০০০",
            }
        },
        {
            'id': 'passport',
            'primary': ['passport taken', 'took my passport', 'holding passport',
                        'employer took passport', 'confiscate passport', 'keep passport',
                        'seized passport', 'cannot get passport', 'agent has passport'],
            'secondary': ['passport', 'confiscate', 'hold', 'take', 'seized', 'embassy'],
            'answers': {
                'en': "🚨 YOUR PASSPORT HAS BEEN TAKEN — This is Illegal\n\nNo employer or agent can legally take or hold your passport in Malaysia. This violates Section 44 of the Anti-Trafficking in Persons Act 2007.\n\nWhat to do RIGHT NOW:\n1. Call JTKSM immediately: 03-8000 8000\n2. Contact your home country's embassy in Kuala Lumpur\n   • Bangladesh High Commission: +60 3-2148 8141\n   • Indonesian Embassy: +60 3-2116 4000\n   • Nepal Embassy: +60 3-2072 2394\n3. Report the agent or employer on MigrantSafe\n4. Do NOT sign any documents under pressure\n\nYou have the right to your passport at all times.",
                'ms': "🚨 PASPORT ANDA DIRAMPAS — Ini Adalah Haram\n\nTiada majikan atau ejen boleh mengambil atau menahan pasport anda di Malaysia. Ini melanggar Akta Anti Pemerdagangan Orang 2007.\n\nApa yang perlu dilakukan SEKARANG:\n1. Hubungi JTKSM segera: 03-8000 8000\n2. Hubungi kedutaan negara asal anda di Kuala Lumpur\n3. Laporkan ejen atau majikan di MigrantSafe\n4. JANGAN tandatangan dokumen di bawah tekanan",
                'bn': "🚨 আপনার পাসপোর্ট নেওয়া হয়েছে — এটি অবৈধ\n\nমালয়েশিয়ায় কোনো নিয়োগকর্তা বা এজেন্ট আপনার পাসপোর্ট আইনত নিতে বা ধরে রাখতে পারবে না।\n\nএখনই যা করবেন:\n১. JTKSM-এ ফোন করুন: ০৩-৮০০০ ৮০০০\n২. কুয়ালালামপুরে আপনার দেশের দূতাবাসে যোগাযোগ করুন\n   • বাংলাদেশ হাই কমিশন: +৬০ ৩-২১৪৮ ৮১৪১\n৩. MigrantSafe-এ রিপোর্ট করুন\n৪. চাপে কোনো কাগজে সই করবেন না",
            }
        },
        {
            'id': 'salary',
            'primary': ['salary not paid', 'wages not paid', 'no salary', 'salary late',
                        'salary withheld', 'money withheld', 'not received salary',
                        'employer not paying', 'deducting too much', 'illegal deduction'],
            'secondary': ['salary', 'wage', 'wages', 'paid', 'payment', 'deduct',
                          'deduction', 'money owed', 'not paid', 'late'],
            'answers': {
                'en': "💵 UNPAID OR WITHHELD SALARY — Know Your Rights\n\nYour employer MUST pay your full salary:\n• On time every month (usually within 7 days of month-end)\n• Without illegal deductions\n• In the correct amount stated in your contract\n\nIllegal deductions include:\n❌ Charging you for recruitment fees\n❌ Deducting more than allowed for accommodation/food\n❌ Withholding salary as punishment or to stop you leaving\n\nWhat to do:\n1. Keep records — take photos of payslips or any evidence\n2. Report to JTKSM: 03-8000 8000\n3. File a complaint at the nearest Labour Department office\n4. Report the employer on MigrantSafe if they are also a registered agent",
                'ms': "💵 GAJI TIDAK DIBAYAR ATAU DITAHAN — Ketahui Hak Anda\n\nMajikan anda MESTI membayar gaji penuh:\n• Tepat masa setiap bulan\n• Tanpa potongan haram\n• Dalam jumlah yang betul seperti dalam kontrak\n\nApa yang perlu dilakukan:\n1. Simpan rekod — ambil gambar slip gaji atau bukti\n2. Laporkan kepada JTKSM: 03-8000 8000\n3. Failkan aduan di pejabat Jabatan Buruh terdekat",
                'bn': "💵 বেতন না পাওয়া বা আটকে রাখা — আপনার অধিকার জানুন\n\nআপনার নিয়োগকর্তাকে অবশ্যই পূর্ণ বেতন দিতে হবে:\n• প্রতি মাসে সময়মতো\n• অবৈধ কাটাকাটি ছাড়া\n• চুক্তিতে উল্লিখিত সঠিক পরিমাণে\n\nআপনি যা করবেন:\n১. প্রমাণ রাখুন — বেতন স্লিপ বা যেকোনো প্রমাণের ছবি তুলুন\n২. JTKSM-এ রিপোর্ট করুন: ০৩-৮০০০ ৮০০০\n৩. নিকটতম শ্রম বিভাগ অফিসে অভিযোগ দাখিল করুন",
            }
        },
        {
            'id': 'contract',
            'primary': ['employment contract', 'work contract', 'sign contract',
                        'what is in contract', 'contract terms', 'blank contract',
                        'contract different', 'job different from contract',
                        'job not as promised', 'job changed', 'different job'],
            'secondary': ['contract', 'sign', 'agreement', 'terms', 'conditions',
                          'promised', 'different', 'job description', 'duties'],
            'answers': {
                'en': "📄 EMPLOYMENT CONTRACT — What You Need to Know\n\nYour contract MUST clearly state:\n✅ Your exact job title and duties\n✅ Monthly salary (exact amount in RM)\n✅ Working hours per day and rest days per week\n✅ Annual leave entitlement\n✅ Accommodation arrangements\n✅ Duration of contract\n✅ Name and address of your employer\n\nImportant rules:\n⚠️ NEVER sign a blank contract\n⚠️ NEVER sign a contract you do not understand — ask for a translated copy\n⚠️ If your actual job is different from what the contract says, this is a violation\n\nIf your job is different from what was promised:\n1. Document the difference in writing\n2. Contact JTKSM: 03-8000 8000\n3. Report the agent on MigrantSafe",
                'ms': "📄 KONTRAK PEKERJAAN — Apa Yang Perlu Anda Tahu\n\nKontrak anda MESTI menyatakan dengan jelas:\n✅ Jawatan dan tugas anda yang tepat\n✅ Gaji bulanan (jumlah tepat dalam RM)\n✅ Waktu kerja dan hari rehat\n✅ Tempoh kontrak\n\nPeraturan penting:\n⚠️ JANGAN tandatangan kontrak kosong\n⚠️ JANGAN tandatangan kontrak yang tidak anda faham\n⚠️ Jika kerja sebenar berbeza dari kontrak, ini adalah pelanggaran\n\nJika kerja berbeza dari yang dijanjikan:\n1. Dokumentasikan perbezaan secara bertulis\n2. Hubungi JTKSM: 03-8000 8000",
                'bn': "📄 চাকরির চুক্তি — আপনার যা জানা দরকার\n\nআপনার চুক্তিতে অবশ্যই স্পষ্টভাবে উল্লেখ থাকতে হবে:\n✅ আপনার সঠিক পদবি ও দায়িত্ব\n✅ মাসিক বেতন (RM-এ সঠিক পরিমাণ)\n✅ দৈনিক কর্মঘণ্টা ও সাপ্তাহিক ছুটির দিন\n✅ চুক্তির মেয়াদ\n\nগুরুত্বপূর্ণ নিয়ম:\n⚠️ কখনো ফাঁকা চুক্তিতে সই করবেন না\n⚠️ যে চুক্তি বুঝতে পারেন না তাতে সই করবেন না\n⚠️ বাস্তব কাজ চুক্তির চেয়ে আলাদা হলে এটি লঙ্ঘন\n\nকাজ প্রতিশ্রুতি থেকে আলাদা হলে JTKSM-এ ফোন করুন: ০৩-৮০০০ ৮০০০",
            }
        },
        {
            'id': 'report',
            'primary': ['how to report', 'report agent', 'file complaint', 'make complaint',
                        'submit report', 'report fraud', 'report scam', 'report cheating',
                        'where to complain', 'agent cheated me', 'agent deceived'],
            'secondary': ['report', 'complain', 'complaint', 'fraud', 'scam', 'cheat',
                          'deceive', 'mislead', 'lodge', 'submit'],
            'answers': {
                'en': "🚨 HOW TO REPORT AN UNETHICAL AGENT\n\nOn MigrantSafe:\n1. Log in to your account\n2. Click 'Report an Agent' in the menu\n3. Enter the agent's name\n4. Select the type of issue (e.g. excessive fees, false job info)\n5. Describe what happened in detail\n6. Submit — admins review within 48 hours\n\n🔒 Your identity is protected. Agents cannot see who filed a report.\n\nYou can also report to:\n• JTKSM (Labour Dept): 03-8000 8000\n• SUHAKAM (Human Rights Commission): 03-2612 5600\n• Your home country's embassy in KL\n\nThe more detail you provide, the faster the admin can act.",
                'ms': "🚨 CARA MELAPORKAN EJEN TIDAK BERETIKA\n\nDi MigrantSafe:\n1. Log masuk ke akaun anda\n2. Klik 'Laporkan Ejen' dalam menu\n3. Masukkan nama ejen\n4. Pilih jenis isu\n5. Huraikan apa yang berlaku secara terperinci\n6. Hantar — admin menyemak dalam 48 jam\n\n🔒 Identiti anda dilindungi. Ejen tidak dapat melihat siapa yang membuat laporan.",
                'bn': "🚨 অনৈতিক এজেন্ট রিপোর্ট করার পদ্ধতি\n\nMigrantSafe-এ:\n১. আপনার অ্যাকাউন্টে লগ ইন করুন\n২. মেনুতে 'এজেন্ট রিপোর্ট করুন' ক্লিক করুন\n৩. এজেন্টের নাম লিখুন\n৪. সমস্যার ধরন বেছে নিন\n৫. কী ঘটেছে বিস্তারিত বর্ণনা করুন\n৬. জমা দিন — অ্যাডমিন ৪৮ ঘণ্টার মধ্যে পর্যালোচনা করবে\n\n🔒 আপনার পরিচয় সুরক্ষিত। এজেন্ট দেখতে পাবে না কে রিপোর্ট করেছে।",
            }
        },
        {
            'id': 'process',
            'primary': ['recruitment process', 'how to come malaysia', 'steps to work malaysia',
                        'how do i apply', 'application process', 'how to get job malaysia',
                        'migrate malaysia', 'work in malaysia how'],
            'secondary': ['process', 'step', 'steps', 'procedure', 'apply', 'arrive',
                          'how', 'stage', 'quota', 'migration'],
            'answers': {
                'en': "🗺️ HOW TO WORK IN MALAYSIA — Step by Step\n\n1️⃣ Apply through a LICENSED recruitment agent\n   → Check the agent on MigrantSafe before paying anything\n\n2️⃣ Your employer applies for a work quota\n   → This is the employer's responsibility, not yours\n\n3️⃣ Medical check in your home country\n   → Some countries require this before departure\n\n4️⃣ Arrive in Malaysia\n\n5️⃣ FOMEMA medical check in Malaysia\n   → Mandatory health screening — usually 1–3 days\n\n6️⃣ VP(TE) work permit visa is processed\n   → Takes 2–6 weeks. You are legally working once this is done.\n\n7️⃣ Begin work legally\n\n⚠️ If at any step an agent asks you for large upfront payments — stop and verify on MigrantSafe or call JTKSM: 03-8000 8000",
                'ms': "🗺️ CARA BEKERJA DI MALAYSIA — Langkah demi Langkah\n\n1️⃣ Mohon melalui ejen pengambilan berlesen\n2️⃣ Majikan memohon kuota kerja\n3️⃣ Pemeriksaan perubatan di negara asal\n4️⃣ Tiba di Malaysia\n5️⃣ Pemeriksaan perubatan FOMEMA di Malaysia (1–3 hari)\n6️⃣ Visa permit kerja VP(TE) diproses (2–6 minggu)\n7️⃣ Mula bekerja secara sah\n\n⚠️ Jika ejen meminta bayaran besar pada mana-mana peringkat — semak di MigrantSafe atau hubungi JTKSM: 03-8000 8000",
                'bn': "🗺️ মালয়েশিয়ায় কাজ করার পদ্ধতি — ধাপে ধাপে\n\n১️⃣ লাইসেন্সপ্রাপ্ত এজেন্টের মাধ্যমে আবেদন করুন\n২️⃣ নিয়োগকর্তা ওয়ার্ক কোটার জন্য আবেদন করে\n৩️⃣ নিজের দেশে মেডিকেল চেক\n৪️⃣ মালয়েশিয়ায় আগমন\n৫️⃣ মালয়েশিয়ায় FOMEMA মেডিকেল চেক (১–৩ দিন)\n৬️⃣ VP(TE) ওয়ার্ক পারমিট ভিসা প্রক্রিয়া (২–৬ সপ্তাহ)\n৭️⃣ বৈধভাবে কাজ শুরু\n\n⚠️ যেকোনো ধাপে এজেন্ট বড় আগাম ফি চাইলে — থামুন এবং MigrantSafe-এ যাচাই করুন বা JTKSM-এ কল করুন: ০৩-৮০০০ ৮০০০",
            }
        },
        {
            'id': 'undocumented',
            'primary': ['undocumented', 'illegal worker', 'overstayed', 'expired visa',
                        'expired permit', 'no valid permit', 'visa expired', 'permit expired',
                        'become illegal', 'how to become legal'],
            'secondary': ['illegal', 'irregular', 'overstay', 'expired', 'undocumented',
                          'document expired', 'out of status'],
            'answers': {
                'en': "⚠️ UNDOCUMENTED STATUS — What You Need to Know\n\nYou can become undocumented (irregular) if:\n• Your VP(TE) work permit expires\n• You change jobs without updating your work pass\n• You fail the FOMEMA medical check\n• Your employer doesn't renew your permit\n• You overstay your allowed duration\n\nIf you think your documents have expired or are invalid:\n1. Do NOT panic — you have options\n2. Contact JTKSM BEFORE it becomes a serious issue: 03-8000 8000\n3. Contact your home country's embassy — they can help\n4. Do not pay unofficial 'fixers' — they often make the situation worse\n\nIt is always better to seek help early than to hide the problem.",
                'ms': "⚠️ STATUS TIDAK BERDOKUMEN — Apa Yang Perlu Anda Tahu\n\nAnda boleh menjadi tidak berdokumen jika:\n• Permit kerja VP(TE) anda tamat tempoh\n• Anda menukar kerja tanpa mengemas kini pas kerja\n• Majikan anda tidak memperbaharui permit anda\n\nJika dokumen anda telah tamat tempoh:\n1. JANGAN panik — anda masih ada pilihan\n2. Hubungi JTKSM SEBELUM ia menjadi masalah serius: 03-8000 8000\n3. Hubungi kedutaan negara asal anda",
                'bn': "⚠️ অনিবন্ধিত স্ট্যাটাস — আপনার যা জানা দরকার\n\nআপনি অনিবন্ধিত হতে পারেন যদি:\n• আপনার VP(TE) ওয়ার্ক পারমিট মেয়াদ উত্তীর্ণ হয়\n• কাজ পরিবর্তন করলে ওয়ার্ক পাস আপডেট না করেন\n• নিয়োগকর্তা পারমিট নবায়ন না করে\n\nডকুমেন্ট মেয়াদ উত্তীর্ণ হলে:\n১. ঘাবড়াবেন না — আপনার কাছে বিকল্প আছে\n২. সমস্যা গুরুতর হওয়ার আগেই JTKSM-এ যোগাযোগ করুন: ০৩-৮০০০ ৮০০০\n৩. আপনার দেশের দূতাবাসে যোগাযোগ করুন",
            }
        },
    ]

    # ── SCORING ENGINE ─────────────────────────────────────────────────────────
    best_score = 0
    best_topic = None

    for topic in TOPICS:
        score = 0
        # Primary keywords are worth 2 points each
        for kw in topic['primary']:
            if kw in low:
                score += 2
        # Secondary keywords are worth 1 point each
        for kw in topic['secondary']:
            if kw in low:
                score += 1
        if score > best_score:
            best_score = score
            best_topic = topic

    # Return the best matching answer if we have any signal at all
    if best_topic and best_score >= 1:
        answers = best_topic['answers']
        lang_answer = answers.get(language) or answers.get('en', '')
        return lang_answer

    # ── SMART CLARIFYING FALLBACK ──────────────────────────────────────────────
    # No keywords matched at all. Give a helpful, specific prompt rather than
    # the generic list — ask the user to rephrase with a concrete topic word.
    clarifiers = {
        'en': (
            "I want to give you an accurate answer, but I need a bit more detail to understand your question. 😊\n\n"
            "Could you try rephrasing and include one of these topics?\n\n"
            "• 💰 Recruitment fees (e.g. 'Is it legal for an agent to charge me fees?')\n"
            "• 🛡️ Agent verification (e.g. 'How do I check if an agent is real?')\n"
            "• 📋 Visa / documents (e.g. 'What documents do I need to work in Malaysia?')\n"
            "• ⚖️ Worker rights (e.g. 'What are my rights if my employer doesn't pay me?')\n"
            "• 🚨 Reporting fraud (e.g. 'How do I report an agent that cheated me?')\n"
            "• 📄 Employment contract (e.g. 'What should my work contract include?')\n\n"
            "If you are in urgent danger, call JTKSM immediately: 03-8000 8000"
        ),
        'ms': (
            "Saya ingin memberikan jawapan yang tepat, tetapi saya memerlukan sedikit lebih banyak maklumat. 😊\n\n"
            "Boleh anda cuba menyatakan semula soalan anda dengan menyebut salah satu topik ini?\n\n"
            "• 💰 Yuran pengambilan\n"
            "• 🛡️ Pengesahan ejen\n"
            "• 📋 Visa / dokumen\n"
            "• ⚖️ Hak pekerja\n"
            "• 🚨 Laporkan penipuan\n"
            "• 📄 Kontrak pekerjaan\n\n"
            "Jika anda dalam bahaya segera, hubungi JTKSM: 03-8000 8000"
        ),
        'bn': (
            "আমি আপনাকে সঠিক উত্তর দিতে চাই, কিন্তু আপনার প্রশ্নটি আরেকটু পরিষ্কার করলে সাহায্য করতে পারব। 😊\n\n"
            "নিচের যেকোনো একটি বিষয় উল্লেখ করে প্রশ্নটি আবার করুন:\n\n"
            "• 💰 রিক্রুটমেন্ট ফি\n"
            "• 🛡️ এজেন্ট যাচাই\n"
            "• 📋 ভিসা / ডকুমেন্ট\n"
            "• ⚖️ শ্রমিকের অধিকার\n"
            "• 🚨 প্রতারণা রিপোর্ট\n"
            "• 📄 চাকরির চুক্তি\n\n"
            "জরুরি বিপদে থাকলে এখনই JTKSM-এ কল করুন: ০৩-৮০০০ ৮০০০"
        ),
    }
    return clarifiers.get(language, clarifiers['en'])


# ─────────────────────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=5000)
