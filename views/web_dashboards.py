from flask import flash, redirect, render_template, request, session, url_for

from auth_utils import login_required, role_required
from db import query_db, rows_to_dicts, row_to_dict
from views.web_shared import (
    AGENT_DASHBOARD_PAGES,
    WORKER_DASHBOARD_PAGES,
    count_rows,
    get_agent_profile_for_user,
    pick_dashboard_page,
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
        WORKER_DASHBOARD_PAGES,
    )

    report_count = count_rows(
        "SELECT COUNT(*) as c FROM reports WHERE worker_id = ?",
        (user_id,),
    )
    enquiry_count = count_rows(
        "SELECT COUNT(*) as c FROM enquiries WHERE worker_id = ?",
        (user_id,),
    )

    stats = {
        'verified': count_rows(
            "SELECT COUNT(*) as c FROM agents WHERE verification_status='verified'",
        ),
        'reported': count_rows(
            "SELECT COUNT(*) as c FROM agents WHERE verification_status='reported'",
        ),
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
        AGENT_DASHBOARD_PAGES,
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
