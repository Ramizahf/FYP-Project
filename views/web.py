import os
import re
import json
from datetime import datetime
from uuid import uuid4

from flask import current_app, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from auth_utils import (
    log_in_user,
    login_required,
    normalize_email,
    role_required,
)
from db import execute_db, query_db, row_to_dict, rows_to_dicts


ROLE_LABELS = {
    'worker': 'Migrant Worker',
    'agent': 'Recruitment Agent',
    'admin': 'Administrator',
}

ENQUIRY_CATEGORIES = (
    'Job Details',
    'Salary and Benefits',
    'Fees and Costs',
    'Documents and Process',
    'Accommodation and Travel',
    'Other',
)

PHONE_RE = re.compile(r'^\+?[0-9]{8,15}$')
PHONE_ERROR = 'Enter a valid phone number!'
REPORT_EVIDENCE_ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'pdf', 'doc', 'docx'}
REPORT_EVIDENCE_MAX_FILES = 5


def is_valid_phone(phone):
    """Allow digits with one optional leading plus, 8-15 digits."""
    return bool(PHONE_RE.fullmatch(phone or ''))


def allowed_report_evidence_file(filename):
    """Return True when filename has an approved evidence extension."""
    return (
        bool(filename)
        and '.' in filename
        and filename.rsplit('.', 1)[1].lower() in REPORT_EVIDENCE_ALLOWED_EXTENSIONS
    )


def get_upload_size(upload):
    """Measure an uploaded file without consuming it."""
    stream = upload.stream
    position = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(position)
    return size


def validate_report_evidence_uploads(uploads):
    """Validate optional report evidence uploads and return error messages."""
    uploads = [upload for upload in uploads if upload and upload.filename]
    if not uploads:
        return None

    errors = []
    if len(uploads) > REPORT_EVIDENCE_MAX_FILES:
        errors.append('You can upload up to 5 evidence files.')

    for upload in uploads:
        if not allowed_report_evidence_file(upload.filename):
            errors.append('Upload evidence must be JPG, PNG, PDF, DOC, or DOCX files only.')
            break
        if get_upload_size(upload) > current_app.config['REPORT_EVIDENCE_MAX_BYTES']:
            errors.append('Each evidence file must be 5MB or smaller.')
            break

    return errors


def save_report_evidence(upload, report_id):
    """Save report evidence using a generated safe filename."""
    original_name = secure_filename(upload.filename)
    if not original_name:
        extension = upload.filename.rsplit('.', 1)[1].lower()
        original_name = f"evidence.{extension}"
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    filename = f"report_{report_id}_{timestamp}_{uuid4().hex[:8]}_{original_name}"
    upload_dir = current_app.config['REPORT_EVIDENCE_FOLDER']
    os.makedirs(upload_dir, exist_ok=True)
    upload.save(os.path.join(upload_dir, filename))
    return f"report_evidence/{filename}"


def save_report_evidence_uploads(uploads, report_id):
    """Save all uploaded evidence files and return their relative paths."""
    return [
        save_report_evidence(upload, report_id)
        for upload in uploads
        if upload and upload.filename
    ]


def pick_dashboard_page(page_name, allowed_pages, default='home'):
    """Return a safe dashboard page name for client-side navigation."""
    return page_name if page_name in allowed_pages else default


def get_agent_profile_for_user(user_id):
    """Fetch the logged-in agent's profile row."""
    return row_to_dict(query_db(
        "SELECT * FROM agents WHERE user_id = ?",
        (user_id,), one=True
    ))


def is_mobile_request():
    """Best-effort mobile detection for routes that are desktop-only."""
    client_hint = request.headers.get('Sec-CH-UA-Mobile', '').strip().lower()
    if client_hint == '?1':
        return True

    user_agent = request.headers.get('User-Agent', '').lower()
    mobile_markers = (
        'android',
        'blackberry',
        'iphone',
        'ipod',
        'mobile',
        'opera mini',
        'windows phone',
    )
    return any(marker in user_agent for marker in mobile_markers)


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
    POST -> Validate, create account, redirect to login with a success message.
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
        elif role == 'worker' and not is_valid_phone(form_data['phone']):
            error = PHONE_ERROR
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


@role_required('worker')
def my_enquiries():
    """Worker can see enquiries sent to agents and any replies."""
    enquiries = rows_to_dicts(query_db(
        """
        SELECT e.*, a.agency_name, a.state
        FROM enquiries e
        JOIN agents a ON a.id = e.agent_id
        WHERE e.worker_id = ?
        ORDER BY e.created_at DESC
        """,
        (session['user_id'],)
    ))
    return render_template('my_enquiries.html', enquiries=enquiries)


def migration_guide():
    """Step-by-step migration process guide."""
    if is_mobile_request():
        return redirect(url_for('dashboard' if 'user_id' in session else 'index'))

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
    initial_page = pick_dashboard_page(
        request.args.get('page', '').strip(),
        {'home', 'profile', 'jobs'},
    )

    my_reports_count = query_db(
        "SELECT COUNT(*) as cnt FROM reports WHERE worker_id = ?",
        (user_id,), one=True
    )
    report_count = my_reports_count['cnt'] if my_reports_count else 0
    my_enquiries_count = query_db(
        "SELECT COUNT(*) as cnt FROM enquiries WHERE worker_id = ?",
        (user_id,), one=True
    )
    enquiry_count = my_enquiries_count['cnt'] if my_enquiries_count else 0

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
    job_preferences = row_to_dict(query_db(
        """
        SELECT desired_job, preferred_location, job_description
        FROM worker_job_preferences
        WHERE worker_id = ?
        """,
        (user_id,), one=True
    ))
    job_listings = rows_to_dicts(query_db(
        """
        SELECT jl.*, a.agency_name
        FROM job_listings jl
        JOIN agents a ON a.id = jl.agent_id
        WHERE jl.status = 'live'
        ORDER BY jl.created_at DESC, jl.id DESC
        """
    ))
    interested_job_ids = {
        row['job_id'] for row in query_db(
            "SELECT job_id FROM job_interests WHERE worker_id = ?",
            (user_id,)
        )
    }

    return render_template(
        'dashboard-worker.html',
        report_count=report_count,
        enquiry_count=enquiry_count,
        stats=stats,
        recent_agents=recent_agents,
        worker_profile=worker_profile,
        job_preferences=job_preferences,
        job_listings=job_listings,
        interested_job_ids=interested_job_ids,
        initial_page=initial_page,
    )


@role_required('agent')
def dashboard_agent():
    """Recruitment agent's dashboard."""
    user_id = session['user_id']
    initial_page = pick_dashboard_page(
        request.args.get('page', '').strip(),
        {'home', 'profile-agency', 'job-listings', 'reviews'},
    )
    agent = get_agent_profile_for_user(user_id)
    if agent:
        for optional_field in ('industry', 'phone', 'description'):
            agent[optional_field] = agent.get(optional_field) or ''

    reports = []
    enquiries = []
    agent_job_listings = []
    if agent:
        reports = rows_to_dicts(query_db(
            "SELECT * FROM reports WHERE agent_id = ? ORDER BY created_at DESC",
            (agent['id'],)
        ))
        enquiries = rows_to_dicts(query_db(
            """
            SELECT e.*, u.full_name AS worker_name, u.email AS worker_email
            FROM enquiries e
            JOIN users u ON u.id = e.worker_id
            WHERE e.agent_id = ?
            ORDER BY
                CASE e.status
                    WHEN 'open' THEN 0
                    WHEN 'replied' THEN 1
                    ELSE 2
                END,
                e.created_at DESC
            """,
            (agent['id'],)
        ))
        agent_job_listings = rows_to_dicts(query_db(
            """
            SELECT *
            FROM job_listings
            WHERE agent_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (agent['id'],)
        ))
        interested_workers = rows_to_dicts(query_db(
            """
            SELECT
                ji.job_id,
                u.id AS worker_id,
                u.full_name AS worker_name,
                u.email AS worker_email,
                wjp.desired_job,
                wjp.preferred_location,
                wjp.job_description
            FROM job_interests ji
            JOIN users u ON u.id = ji.worker_id
            LEFT JOIN worker_job_preferences wjp ON wjp.worker_id = u.id
            JOIN job_listings jl ON jl.id = ji.job_id
            WHERE jl.agent_id = ? AND u.role = 'worker'
            ORDER BY ji.created_at DESC, u.full_name ASC
            """,
            (agent['id'],)
        ))
        interested_by_job = {}
        for worker in interested_workers:
            interested_by_job.setdefault(worker['job_id'], []).append(worker)
        for listing in agent_job_listings:
            listing['interested_workers'] = interested_by_job.get(listing['id'], [])
            listing['interest_count'] = len(listing['interested_workers'])

    profile_views = 0

    return render_template(
        'dashboard-agent.html',
        agent=agent,
        reports=reports,
        enquiries=enquiries,
        profile_views=profile_views,
        agent_job_listings=agent_job_listings,
        initial_page=initial_page,
    )


def submit_enquiry():
    """Worker-only enquiry form for contacting an agent inside the platform."""
    if 'user_id' not in session:
        flash('Please log in to send an enquiry.', 'warning')
        return redirect(url_for('login'))
    if session.get('role') != 'worker':
        flash('Only workers can send enquiries to agents.', 'warning')
        return redirect(url_for('dashboard'))

    agent_id_param = request.args.get('agent_id') or request.form.get('agent_id')
    if not agent_id_param:
        flash('Please choose an agent first, then send your enquiry from the agent page.', 'warning')
        return redirect(url_for('agents'))

    agent = row_to_dict(query_db(
        "SELECT * FROM agents WHERE id = ?",
        (agent_id_param,), one=True
    ))
    if not agent:
        flash('Agent not found.', 'danger')
        return redirect(url_for('agents'))

    form_data = {
        'subject': request.form.get('subject', '').strip(),
        'category': request.form.get('category', '').strip(),
        'message': request.form.get('message', '').strip(),
    }

    if request.method == 'POST':
        errors = []
        if not form_data['subject']:
            errors.append('Please enter a subject for your enquiry.')
        elif len(form_data['subject']) < 3:
            errors.append('Subject must be at least 3 characters.')
        elif len(form_data['subject']) > 150:
            errors.append('Subject is too long (max 150 characters).')

        if form_data['category'] not in ENQUIRY_CATEGORIES:
            errors.append('Please choose a valid enquiry category.')

        if not form_data['message']:
            errors.append('Please write your message.')
        elif len(form_data['message']) < 10:
            errors.append('Message must be at least 10 characters.')
        elif len(form_data['message']) > 2000:
            errors.append('Message is too long (max 2000 characters).')

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            execute_db(
                """
                INSERT INTO enquiries
                    (worker_id, agent_id, subject, category, message)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session['user_id'],
                    agent['id'],
                    form_data['subject'],
                    form_data['category'],
                    form_data['message'],
                )
            )
            flash('Your enquiry has been sent through MigrantSafe. Please wait for the agent reply here.', 'success')
            return redirect(url_for('my_enquiries'))

    return render_template(
        'enquiry_form.html',
        agent=agent,
        enquiry_categories=ENQUIRY_CATEGORIES,
        form_data=form_data,
    )


@role_required('agent')
def reply_enquiry(enquiry_id):
    """Agent replies to a worker enquiry and sets its ticket status."""
    agent = row_to_dict(query_db(
        "SELECT * FROM agents WHERE user_id = ?",
        (session['user_id'],), one=True
    ))
    if not agent:
        flash('Please complete your agency profile before managing enquiries.', 'warning')
        return redirect(url_for('dashboard_agent'))

    enquiry = row_to_dict(query_db(
        "SELECT * FROM enquiries WHERE id = ? AND agent_id = ?",
        (enquiry_id, agent['id']), one=True
    ))
    if not enquiry:
        flash('Enquiry not found.', 'danger')
        return redirect(url_for('dashboard_agent'))

    reply_message = request.form.get('reply_message', '').strip()
    new_status = request.form.get('status', 'replied').strip().lower()

    if new_status not in ('replied', 'closed'):
        flash('Please choose a valid status.', 'danger')
        return redirect(url_for('dashboard_agent'))

    if not reply_message:
        flash('Please write a reply before updating the enquiry.', 'danger')
        return redirect(url_for('dashboard_agent'))
    if len(reply_message) < 5:
        flash('Reply must be at least 5 characters.', 'danger')
        return redirect(url_for('dashboard_agent'))
    if len(reply_message) > 2000:
        flash('Reply is too long (max 2000 characters).', 'danger')
        return redirect(url_for('dashboard_agent'))

    execute_db(
        """
        UPDATE enquiries
        SET reply_message = ?, status = ?, replied_at = datetime('now')
        WHERE id = ?
        """,
        (reply_message, new_status, enquiry_id)
    )
    flash('Enquiry reply saved.', 'success')
    return redirect(url_for('dashboard_agent', page='reviews'))


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

    form_data = {
        'agent_id': str(agent['id']) if agent else '',
        'agent_staff_name': '',
        'report_reason': '',
        'description': '',
        'incident_date': ''
    }

    if request.method == 'POST':
        agent_id = request.form.get('agent_id', '').strip()
        agent_staff_name = request.form.get('agent_staff_name', '').strip()
        report_reason = request.form.get('report_reason', '').strip()
        description = request.form.get('description', '').strip()
        incident_date = request.form.get('incident_date', '').strip() or None
        evidence_uploads = request.files.getlist('evidence')
        selected_agent = row_to_dict(query_db(
            "SELECT id, agency_name FROM agents WHERE id = ?",
            (agent_id,), one=True
        )) if agent_id else None
        agent_name = selected_agent['agency_name'] if selected_agent else ''

        form_data = {
            'agent_id': agent_id,
            'agent_staff_name': agent_staff_name,
            'report_reason': report_reason,
            'description': description,
            'incident_date': incident_date or ''
        }

        errors = []
        if not agent_id:
            errors.append('Please select an agency name.')
        elif not selected_agent:
            errors.append('Please select a valid agency from the list.')

        if agent_staff_name and len(agent_staff_name) > 200:
            errors.append('Agent / Staff Name is too long (max 200 characters).')

        if not report_reason:
            errors.append('Please select the type of issue.')

        if not description:
            errors.append('Please describe what happened.')
        elif len(description) < 20:
            errors.append('Please provide more detail (at least 20 characters).')
        elif len(description) > 2000:
            errors.append('Description is too long (max 2000 characters).')

        evidence_errors = validate_report_evidence_uploads(evidence_uploads)
        if evidence_errors:
            errors.extend(evidence_errors)

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            report_id = execute_db(
                """
                INSERT INTO reports
                    (worker_id, agent_id, agent_name, agent_staff_name, report_reason, description, incident_date)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session['user_id'],
                    selected_agent['id'],
                    agent_name,
                    agent_staff_name or None,
                    report_reason,
                    description,
                    incident_date
                )
            )
            evidence_paths = save_report_evidence_uploads(evidence_uploads, report_id)
            if evidence_paths:
                execute_db(
                    "UPDATE reports SET evidence_path = ? WHERE id = ?",
                    (json.dumps(evidence_paths), report_id)
                )
            flash('Your report has been submitted. Our admin team will review it within 48 hours.', 'success')
            return redirect(url_for('my_reports'))

    all_agents = rows_to_dicts(query_db("SELECT * FROM agents ORDER BY agency_name"))
    return render_template('report.html', agent=agent, all_agents=all_agents, form_data=form_data)


@role_required('worker')
def update_worker_profile():
    """Allow a logged-in worker to update their country and phone number."""
    user_id = session['user_id']
    country = request.form.get('country', '').strip()
    phone = request.form.get('phone', '').strip()

    if phone and not is_valid_phone(phone):
        flash(PHONE_ERROR, 'danger')
        return redirect(url_for('dashboard_worker'))

    execute_db(
        "UPDATE users SET country = ?, phone = ? WHERE id = ?",
        (country or None, phone or None, user_id)
    )

    flash('Profile updated successfully.', 'success')
    return redirect(url_for('dashboard_worker', page='profile'))


@role_required('worker')
def update_worker_job_preferences():
    """Save a worker's job preference details."""
    user_id = session['user_id']
    desired_job = request.form.get('desired_job', '').strip()
    preferred_location = request.form.get('preferred_location', '').strip()
    job_description = request.form.get('job_description', '').strip()

    if not desired_job:
        flash('Please enter the type of job you are looking for.', 'danger')
        return redirect(url_for('dashboard_worker', page='profile'))
    if len(desired_job) > 150:
        flash('Desired job is too long (max 150 characters).', 'danger')
        return redirect(url_for('dashboard_worker', page='profile'))
    if len(preferred_location) > 150:
        flash('Preferred location is too long (max 150 characters).', 'danger')
        return redirect(url_for('dashboard_worker', page='profile'))
    if len(job_description) > 1000:
        flash('Job description is too long (max 1000 characters).', 'danger')
        return redirect(url_for('dashboard_worker', page='profile'))

    existing_preferences = query_db(
        "SELECT id FROM worker_job_preferences WHERE worker_id = ?",
        (user_id,), one=True
    )

    if existing_preferences:
        execute_db(
            """
            UPDATE worker_job_preferences
            SET desired_job = ?, preferred_location = ?, job_description = ?
            WHERE worker_id = ?
            """,
            (
                desired_job,
                preferred_location or None,
                job_description or None,
                user_id,
            )
        )
    else:
        execute_db(
            """
            INSERT INTO worker_job_preferences
                (worker_id, desired_job, preferred_location, job_description)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_id,
                desired_job,
                preferred_location or None,
                job_description or None,
            )
        )

    flash('Job preferences saved.', 'success')
    return redirect(url_for('dashboard_worker', page='profile'))


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

    if phone and not is_valid_phone(phone):
        errors.append(PHONE_ERROR)

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
    return redirect(url_for('dashboard_agent', page='profile-agency'))


@role_required('agent')
def create_job_listing():
    """Allow an agent to create a basic job listing."""
    agent = get_agent_profile_for_user(session['user_id'])
    if not agent:
        flash('Please complete your agency profile before posting a job listing.', 'warning')
        return redirect(url_for('dashboard_agent', page='profile-agency'))

    job_title = request.form.get('job_title', '').strip()
    location = request.form.get('location', '').strip()
    description = request.form.get('description', '').strip()

    if not job_title:
        flash('Please enter a job title.', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))
    if not location:
        flash('Please enter a job location.', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))
    if not description:
        flash('Please enter a short job description.', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))
    if len(job_title) > 150:
        flash('Job title is too long (max 150 characters).', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))
    if len(location) > 150:
        flash('Location is too long (max 150 characters).', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))
    if len(description) > 1000:
        flash('Description is too long (max 1000 characters).', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))

    execute_db(
        """
        INSERT INTO job_listings (agent_id, job_title, location, description, status)
        VALUES (?, ?, ?, ?, 'live')
        """,
        (agent['id'], job_title, location, description)
    )

    flash('Job listing published.', 'success')
    return redirect(url_for('dashboard_agent', page='job-listings'))


@role_required('agent')
def close_job_listing(job_id):
    """Allow an agent to close one of their own job listings."""
    agent = get_agent_profile_for_user(session['user_id'])
    if not agent:
        flash('Please complete your agency profile before managing job listings.', 'warning')
        return redirect(url_for('dashboard_agent', page='profile-agency'))

    listing = query_db(
        "SELECT id, status FROM job_listings WHERE id = ? AND agent_id = ?",
        (job_id, agent['id']),
        one=True,
    )
    if not listing:
        flash('Job listing not found.', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))

    if listing['status'] == 'closed':
        flash('Job is already closed.', 'info')
        return redirect(url_for('dashboard_agent', page='job-listings'))

    execute_db(
        "UPDATE job_listings SET status = 'closed' WHERE id = ? AND agent_id = ?",
        (job_id, agent['id']),
    )
    flash('Job closed.', 'success')
    return redirect(url_for('dashboard_agent', page='job-listings'))


@role_required('agent')
def agent_worker_profile(worker_id):
    """Show a simple worker profile to an agent when the worker expressed interest."""
    agent = get_agent_profile_for_user(session['user_id'])
    if not agent:
        flash('Please complete your agency profile first.', 'warning')
        return redirect(url_for('dashboard_agent', page='profile-agency'))

    worker = row_to_dict(query_db(
        """
        SELECT
            u.id AS worker_id,
            u.full_name AS worker_name,
            wjp.desired_job,
            wjp.preferred_location,
            wjp.job_description
        FROM users u
        LEFT JOIN worker_job_preferences wjp ON wjp.worker_id = u.id
        WHERE u.id = ?
          AND u.role = 'worker'
          AND EXISTS (
              SELECT 1
              FROM job_interests ji
              JOIN job_listings jl ON jl.id = ji.job_id
              WHERE ji.worker_id = u.id
                AND jl.agent_id = ?
          )
        """,
        (worker_id, agent['id']), one=True
    ))
    if not worker:
        flash('Worker not found or you do not have access to this profile.', 'danger')
        return redirect(url_for('dashboard_agent', page='job-listings'))

    return render_template(
        'agent-worker-profile.html',
        agent=agent,
        worker=worker,
        back_url=request.referrer or url_for('dashboard_agent', page='job-listings'),
    )


@role_required('worker')
def send_job_interest(job_id):
    """Save that a worker is interested in a job listing."""
    job_listing = query_db(
        "SELECT id FROM job_listings WHERE id = ?",
        (job_id,), one=True
    )
    if not job_listing:
        flash('Job listing not found.', 'danger')
        return redirect(url_for('dashboard_worker', page='jobs'))

    existing_interest = query_db(
        "SELECT id FROM job_interests WHERE worker_id = ? AND job_id = ?",
        (session['user_id'], job_id), one=True
    )
    if not existing_interest:
        execute_db(
            "INSERT INTO job_interests (worker_id, job_id) VALUES (?, ?)",
            (session['user_id'], job_id)
        )

    flash('Interest sent. Agent can view your profile.', 'success')
    return redirect(url_for('dashboard_worker', page='jobs'))


def register_web_routes(app):
    """Register public/auth/dashboard/report routes with stable endpoints."""
    app.add_url_rule('/', endpoint='index', view_func=index)
    app.add_url_rule('/agents', endpoint='agents', view_func=agents)
    app.add_url_rule('/login', endpoint='login', view_func=login, methods=['GET', 'POST'])
    app.add_url_rule('/register', endpoint='register', view_func=register, methods=['GET', 'POST'])
    app.add_url_rule('/logout', endpoint='logout', view_func=logout)
    app.add_url_rule('/agents/<int:agent_id>', endpoint='agent_detail', view_func=agent_detail)
    app.add_url_rule('/my-reports', endpoint='my_reports', view_func=my_reports)
    app.add_url_rule('/my-enquiries', endpoint='my_enquiries', view_func=my_enquiries)
    app.add_url_rule('/guide', endpoint='migration_guide', view_func=migration_guide)
    app.add_url_rule('/dashboard', endpoint='dashboard', view_func=dashboard)
    app.add_url_rule('/dashboard/worker', endpoint='dashboard_worker', view_func=dashboard_worker)
    app.add_url_rule('/dashboard/agent', endpoint='dashboard_agent', view_func=dashboard_agent)
    app.add_url_rule('/enquiry', endpoint='submit_enquiry', view_func=submit_enquiry, methods=['GET', 'POST'])
    app.add_url_rule('/agent/enquiry/<int:enquiry_id>/reply', endpoint='reply_enquiry', view_func=reply_enquiry, methods=['POST'])
    app.add_url_rule('/agent/worker/<int:worker_id>', endpoint='agent_worker_profile', view_func=agent_worker_profile)
    app.add_url_rule('/report', endpoint='submit_report', view_func=submit_report, methods=['GET', 'POST'])
    app.add_url_rule('/job/<int:job_id>/interest', endpoint='send_job_interest', view_func=send_job_interest, methods=['POST'])
    app.add_url_rule('/worker/profile', endpoint='update_worker_profile', view_func=update_worker_profile, methods=['POST'])
    app.add_url_rule('/worker/job-preferences', endpoint='update_worker_job_preferences', view_func=update_worker_job_preferences, methods=['POST'])
    app.add_url_rule('/agent/profile', endpoint='update_agent_profile', view_func=update_agent_profile, methods=['POST'])
    app.add_url_rule('/agent/job-listings', endpoint='create_job_listing', view_func=create_job_listing, methods=['POST'])
    app.add_url_rule('/agent/job/<int:job_id>/close', endpoint='close_job_listing', view_func=close_job_listing, methods=['POST'])
