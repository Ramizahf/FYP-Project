from flask import flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import login_required, role_required
from db import execute_db, query_db, row_to_dict, rows_to_dicts


def index():
    """Landing page - public, no login required."""
    return render_template('index.html')


def agents():
    """
    Public agents directory.
    Supports search (q=) and status filter (status=verified|pending|reported).
    """
    q = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()

    sql = "SELECT * FROM agents WHERE 1=1"
    params = []

    if q:
        sql += " AND (agency_name LIKE ? OR state LIKE ? OR industry LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like]

    if status in ('verified', 'pending', 'reported'):
        sql += " AND verification_status = ?"
        params.append(status)

    sql += " ORDER BY verification_status ASC, agency_name ASC"

    all_agents = rows_to_dicts(query_db(sql, params))
    all_for_stats = query_db("SELECT verification_status FROM agents")
    stats = {
        'total': len(all_for_stats),
        'verified': sum(1 for a in all_for_stats if a['verification_status'] == 'verified'),
        'pending': sum(1 for a in all_for_stats if a['verification_status'] == 'pending'),
        'reported': sum(1 for a in all_for_stats if a['verification_status'] == 'reported'),
    }

    return render_template(
        'agents.html',
        agents=all_agents,
        stats=stats,
        q=q,
        status_filter=status,
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
        email = request.form.get('email', '').strip().lower()
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
                session.clear()
                session.permanent = True
                session['user_id'] = user['id']
                session['name'] = user['full_name']
                session['email'] = user['email']
                session['role'] = user['role']

                role_labels = {
                    'worker': 'Migrant Worker',
                    'agent': 'Recruitment Agent',
                    'admin': 'Administrator'
                }
                flash(
                    f"Welcome back, {user['full_name']}! "
                    f"Logged in as {role_labels.get(user['role'], user['role'])}.",
                    'success'
                )
                return redirect(url_for('dashboard'))

            error = 'Incorrect email or password. Please try again.'

    return render_template('login.html', error=error)


def register():
    """
    GET  -> Show the registration form.
    POST -> Validate, create account, redirect to login with a success message.
    """
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    error = None
    form_data = {}

    if request.method == 'POST':
        role = request.form.get('role', 'worker').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()

        form_data = {
            'role': role,
            'email': email,
            'first_name': request.form.get('first_name', '').strip(),
            'last_name': request.form.get('last_name', '').strip(),
            'country': request.form.get('country', '').strip(),
            'phone': request.form.get('phone', '').strip(),
            'agency_name': request.form.get('agency_name', '').strip(),
            'reg_num': request.form.get('reg_num', '').strip(),
            'agent_state': request.form.get('agent_state', '').strip(),
        }

        full_name = (
            f"{form_data['first_name']} {form_data['last_name']}".strip()
            if role == 'worker'
            else form_data['agency_name']
        )

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
    name = session.get('name', '')
    session.clear()
    flash(f'You have been logged out{", " + name if name else ""}. See you next time!', 'info')
    return redirect(url_for('index'))


def agent_detail(agent_id):
    """Public profile page for a single agent."""
    agent = row_to_dict(query_db(
        "SELECT * FROM agents WHERE id = ?",
        (agent_id,), one=True
    ))
    if not agent:
        flash('Agent not found.', 'danger')
        return redirect(url_for('agents'))

    report_count = query_db(
        "SELECT COUNT(*) as c FROM reports WHERE agent_id = ? AND status = 'open'",
        (agent_id,), one=True
    )['c']

    return render_template(
        'agent_detail.html',
        agent=agent,
        report_count=report_count,
    )


@role_required('worker')
def my_reports():
    """Worker can see all reports they have submitted and their current status."""
    reports = rows_to_dicts(query_db(
        "SELECT * FROM reports WHERE worker_id = ? ORDER BY created_at DESC",
        (session['user_id'],)
    ))
    return render_template('my_reports.html', reports=reports)


def migration_guide():
    """Step-by-step migration process guide."""
    return render_template('guide.html')


@login_required
def dashboard():
    """Send the user to whichever dashboard matches their role."""
    role = session.get('role')
    if role == 'worker':
        return redirect(url_for('dashboard_worker'))
    if role == 'agent':
        return redirect(url_for('dashboard_agent'))
    if role == 'admin':
        return redirect(url_for('dashboard_admin'))

    session.clear()
    flash('Your account role is not recognised. Please contact support.', 'danger')
    return redirect(url_for('login'))


@role_required('worker')
def dashboard_worker():
    """Worker's personal dashboard."""
    user_id = session['user_id']

    my_reports_count = query_db(
        "SELECT COUNT(*) as cnt FROM reports WHERE worker_id = ?",
        (user_id,), one=True
    )
    report_count = my_reports_count['cnt'] if my_reports_count else 0

    stats = {
        'verified': query_db(
            "SELECT COUNT(*) as c FROM agents WHERE verification_status='verified'",
            one=True
        )['c'],
        'reported': query_db(
            "SELECT COUNT(*) as c FROM agents WHERE verification_status='reported'",
            one=True
        )['c'],
    }

    recent_agents = rows_to_dicts(query_db(
        "SELECT * FROM agents ORDER BY id DESC LIMIT 4"
    ))

    worker_profile = row_to_dict(query_db(
        "SELECT country, phone FROM users WHERE id = ?",
        (user_id,), one=True
    ))

    return render_template(
        'dashboard-worker.html',
        report_count=report_count,
        stats=stats,
        recent_agents=recent_agents,
        worker_profile=worker_profile,
    )


@role_required('agent')
def dashboard_agent():
    """Recruitment agent's dashboard."""
    user_id = session['user_id']

    agent = row_to_dict(query_db(
        "SELECT * FROM agents WHERE user_id = ?",
        (user_id,), one=True
    ))

    reports = []
    if agent:
        reports = rows_to_dicts(query_db(
            "SELECT * FROM reports WHERE agent_id = ? ORDER BY created_at DESC",
            (agent['id'],)
        ))

    open_report_count = sum(1 for r in reports if r['status'] == 'open')
    profile_views = 0
    average_rating = None

    return render_template(
        'dashboard-agent.html',
        agent=agent,
        reports=reports,
        open_report_count=open_report_count,
        profile_views=profile_views,
        average_rating=average_rating,
    )


def submit_report():
    """
    Worker-only report submission.
    GET  -> Show report form.
    POST -> Validate and save report to database.
    """
    if 'user_id' not in session:
        flash('Please log in to submit a report.', 'warning')
        return redirect(url_for('login'))
    if session.get('role') != 'worker':
        flash('Only workers can submit reports.', 'warning')
        return redirect(url_for('dashboard'))

    agent_id_param = request.args.get('agent_id')
    agent = None
    if agent_id_param:
        agent = row_to_dict(query_db(
            "SELECT * FROM agents WHERE id = ?",
            (agent_id_param,), one=True
        ))

    if request.method == 'POST':
        agent_name = request.form.get('agent_name', '').strip()
        agent_id = request.form.get('agent_id') or None
        report_reason = request.form.get('report_reason', '').strip()
        description = request.form.get('description', '').strip()
        incident_date = request.form.get('incident_date', '').strip() or None

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
            for error in errors:
                flash(error, 'danger')
        else:
            execute_db(
                """
                INSERT INTO reports
                    (worker_id, agent_id, agent_name, report_reason, description, incident_date)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session['user_id'], agent_id, agent_name, report_reason, description, incident_date)
            )
            flash('Your report has been submitted. Our admin team will review it within 48 hours.', 'success')
            return redirect(url_for('my_reports'))

    all_agents = rows_to_dicts(query_db("SELECT * FROM agents ORDER BY agency_name"))
    return render_template('report.html', agent=agent, all_agents=all_agents)


@role_required('worker')
def update_worker_profile():
    """Allow a logged-in worker to update their country and phone number."""
    user_id = session['user_id']
    country = request.form.get('country', '').strip()
    phone = request.form.get('phone', '').strip()

    if phone and len(phone) > 20:
        flash('Phone number is too long (max 20 characters).', 'danger')
        return redirect(url_for('dashboard_worker'))

    execute_db(
        "UPDATE users SET country = ?, phone = ? WHERE id = ?",
        (country or None, phone or None, user_id)
    )

    flash('Profile updated successfully.', 'success')
    return redirect(url_for('dashboard_worker'))


@role_required('agent')
def update_agent_profile():
    """Save changes to an agent's own profile."""
    user_id = session['user_id']
    agent = row_to_dict(query_db("SELECT * FROM agents WHERE user_id = ?", (user_id,), one=True))

    agency_name = request.form.get('agency_name', '').strip()
    license_number = request.form.get('license_number', '').strip()
    state = request.form.get('state', '').strip()
    industry = request.form.get('industry', '').strip()
    phone = request.form.get('phone', '').strip()
    description = request.form.get('description', '').strip()

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
        for error in errors:
            flash(error, 'danger')
        return redirect(url_for('dashboard_agent'))

    if agent:
        execute_db(
            """
            UPDATE agents
            SET agency_name = ?, license_number = ?, state = ?,
                industry = ?, phone = ?, description = ?
            WHERE user_id = ?
            """,
            (agency_name, license_number, state, industry, phone, description, user_id)
        )
    else:
        execute_db(
            """
            INSERT INTO agents (user_id, agency_name, license_number, state, industry, phone, email)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, agency_name, license_number, state, industry, phone, session.get('email', ''))
        )

    session['name'] = agency_name
    flash('Profile saved! Admins will be notified to review your details.', 'success')
    return redirect(url_for('dashboard_agent'))


def register_web_routes(app):
    """Register public/auth/dashboard/report routes with stable endpoints."""
    app.add_url_rule('/', endpoint='index', view_func=index)
    app.add_url_rule('/agents', endpoint='agents', view_func=agents)
    app.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    app.add_url_rule('/register', endpoint='register', view_func=register, methods=['GET', 'POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=logout)
    app.add_url_rule('/agents/<int:agent_id>', endpoint='agent_detail', view_func=agent_detail)
    app.add_url_rule('/my-reports', endpoint='my_reports', view_func=my_reports)
    app.add_url_rule('/guide', endpoint='migration_guide', view_func=migration_guide)
    app.add_url_rule('/dashboard', endpoint='dashboard', view_func=dashboard)
    app.add_url_rule('/dashboard/worker', endpoint='dashboard_worker', view_func=dashboard_worker)
    app.add_url_rule('/dashboard/agent', endpoint='dashboard_agent', view_func=dashboard_agent)
    app.add_url_rule('/report', endpoint='submit_report', view_func=submit_report, methods=['GET', 'POST'])
    app.add_url_rule('/worker/profile', endpoint='update_worker_profile', view_func=update_worker_profile, methods=['POST'])
    app.add_url_rule('/agent/profile', endpoint='update_agent_profile', view_func=update_agent_profile, methods=['POST'])
