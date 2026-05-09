import json
from uuid import uuid4

from flask import flash, redirect, render_template, request, session, url_for

from auth_utils import role_required
from db import IntegrityError, execute_db, query_db, row_to_dict, rows_to_dicts
from views.web_shared import (
    ENQUIRY_CATEGORIES,
    flash_errors,
    save_report_evidence_uploads,
    validate_enquiry,
    validate_report_form,
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
        'submission_token': request.form.get('submission_token', '').strip() or uuid4().hex,
    }

    if request.method == 'POST':
        errors = validate_enquiry(form_data)

        if errors:
            flash_errors(errors)
        else:
            existing_enquiry = query_db(
                """
                SELECT id
                FROM enquiries
                WHERE worker_id = ?
                  AND agent_id = ?
                  AND subject = ?
                  AND category = ?
                  AND message = ?
                  AND status = 'open'
                  AND reply_message IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (
                    session['user_id'],
                    agent['id'],
                    form_data['subject'],
                    form_data['category'],
                    form_data['message'],
                ),
                one=True,
            )
            if existing_enquiry:
                flash('This enquiry was already sent and is waiting for the agent reply.', 'warning')
                return redirect(url_for('my_enquiries'))

            try:
                execute_db(
                    """
                    INSERT INTO enquiries
                        (worker_id, agent_id, subject, category, message, idempotency_key)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session['user_id'],
                        agent['id'],
                        form_data['subject'],
                        form_data['category'],
                        form_data['message'],
                        form_data['submission_token'],
                    )
                )
                flash('Your enquiry has been sent through MigrantSafe. Please wait for the agent reply here.', 'success')
            except IntegrityError:
                flash('This enquiry was already sent and is waiting for the agent reply.', 'warning')
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
        incident_date = request.form.get('incident_date', '').strip() or None
        evidence_uploads = request.files.getlist('evidence')
        selected_agent = row_to_dict(query_db(
            "SELECT id, agency_name FROM agents WHERE id = ?",
            (agent_id,), one=True
        )) if agent_id else None
        agent_name = selected_agent['agency_name'] if selected_agent else ''

        form_data = {
            'agent_id': agent_id,
            'agent_staff_name': request.form.get('agent_staff_name', '').strip(),
            'report_reason': request.form.get('report_reason', '').strip(),
            'description': request.form.get('description', '').strip(),
            'incident_date': incident_date or ''
        }

        errors = validate_report_form(form_data, selected_agent, evidence_uploads)

        if errors:
            flash_errors(errors)
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
                    form_data['agent_staff_name'] or None,
                    form_data['report_reason'],
                    form_data['description'],
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
