from flask import flash, redirect, render_template, request, session, url_for

from auth_utils import role_required
from db import execute_db, query_db, row_to_dict
from views.web_shared import (
    PHONE_ERROR,
    flash_errors,
    get_agent_profile_for_user,
    is_valid_phone,
    redirect_dashboard_page,
    validate_job_listing,
)


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
        flash_errors(errors)
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

    errors = validate_job_listing(job_title, location, description)
    if errors:
        flash_errors(errors)
        return redirect_dashboard_page('dashboard_agent', 'job-listings')

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
