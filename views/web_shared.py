import os
import re

from flask import current_app, flash, redirect, request, url_for

from db import query_db, row_to_dict
from evidence_storage import make_report_evidence_record


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
VALID_AGENT_STATUSES = ('verified', 'pending', 'reported')
WORKER_DASHBOARD_PAGES = {'home', 'profile', 'jobs'}
AGENT_DASHBOARD_PAGES = {'home', 'profile-agency', 'job-listings', 'reviews'}


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
    """Store report evidence in the database so it survives Vercel deployments."""
    return make_report_evidence_record(upload, report_id)


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


def count_rows(sql, args=()):
    """Return a COUNT(*) result with a stable zero fallback."""
    row = query_db(sql, args, one=True)
    return row['c'] if row else 0


def flash_errors(errors):
    """Display a list of validation errors."""
    for error in errors:
        flash(error, 'danger')


def redirect_dashboard_page(endpoint, page):
    """Redirect to a specific dashboard tab."""
    return redirect(url_for(endpoint, page=page))


def get_registration_form_data(role, email):
    """Collect and trim registration fields from the current request."""
    return {
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


def registration_full_name(form_data):
    """Return the user's display name for worker or agent registration."""
    if form_data['role'] == 'worker':
        return f"{form_data['first_name']} {form_data['last_name']}".strip()
    return form_data['agency_name']


def validate_registration(form_data, password, confirm):
    """Return the first registration validation error, if any."""
    role = form_data['role']
    full_name = registration_full_name(form_data)

    if role not in ('worker', 'agent'):
        return 'Please select Worker or Agent.'
    if not full_name:
        return 'Please enter your full name.' if role == 'worker' else 'Please enter your agency name.'
    if not form_data['email'] or '@' not in form_data['email'] or '.' not in form_data['email']:
        return 'Please enter a valid email address.'
    if len(password) < 8:
        return 'Password must be at least 8 characters.'
    if not any(c.isupper() for c in password):
        return 'Password must contain at least one uppercase letter (e.g. A, B, C).'
    if not any(c.isdigit() for c in password):
        return 'Password must contain at least one number (e.g. 1, 2, 3).'
    if password != confirm:
        return 'Passwords do not match.'
    if role == 'worker' and not is_valid_phone(form_data['phone']):
        return PHONE_ERROR
    if role == 'agent' and not form_data['reg_num']:
        return 'Please enter your JTK registration number.'
    if role == 'agent' and not form_data['agent_state']:
        return 'Please select your state / location.'
    return None


def validate_enquiry(form_data):
    """Return validation errors for a worker enquiry."""
    errors = []
    subject = form_data['subject']
    message = form_data['message']

    if not subject:
        errors.append('Please enter a subject for your enquiry.')
    elif len(subject) < 3:
        errors.append('Subject must be at least 3 characters.')
    elif len(subject) > 150:
        errors.append('Subject is too long (max 150 characters).')

    if form_data['category'] not in ENQUIRY_CATEGORIES:
        errors.append('Please choose a valid enquiry category.')

    if not message:
        errors.append('Please write your message.')
    elif len(message) < 10:
        errors.append('Message must be at least 10 characters.')
    elif len(message) > 2000:
        errors.append('Message is too long (max 2000 characters).')

    return errors


def validate_report_form(form_data, selected_agent, evidence_uploads):
    """Return validation errors for a worker report."""
    errors = []

    if not form_data['agent_id']:
        errors.append('Please select an agency name.')
    elif not selected_agent:
        errors.append('Please select a valid agency from the list.')

    if form_data['agent_staff_name'] and len(form_data['agent_staff_name']) > 200:
        errors.append('Agent / Staff Name is too long (max 200 characters).')

    if not form_data['report_reason']:
        errors.append('Please select the type of issue.')

    description = form_data['description']
    if not description:
        errors.append('Please describe what happened.')
    elif len(description) < 20:
        errors.append('Please provide more detail (at least 20 characters).')
    elif len(description) > 2000:
        errors.append('Description is too long (max 2000 characters).')

    evidence_errors = validate_report_evidence_uploads(evidence_uploads)
    if evidence_errors:
        errors.extend(evidence_errors)

    return errors


def validate_job_listing(job_title, location, description):
    """Return validation errors for a new job listing."""
    errors = []
    if not job_title:
        errors.append('Please enter a job title.')
    if not location:
        errors.append('Please enter a job location.')
    if not description:
        errors.append('Please enter a short job description.')
    if len(job_title) > 150:
        errors.append('Job title is too long (max 150 characters).')
    if len(location) > 150:
        errors.append('Location is too long (max 150 characters).')
    if len(description) > 1000:
        errors.append('Description is too long (max 1000 characters).')
    return errors
