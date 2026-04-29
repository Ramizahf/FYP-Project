import os
import json

from flask import abort, current_app, flash, redirect, render_template, request, send_from_directory, session, url_for

from auth_utils import role_required
from db import execute_db, query_db, row_to_dict, rows_to_dicts


def parse_report_evidence_paths(evidence_path):
    """Return stored report evidence paths as a list."""
    if not evidence_path:
        return []
    try:
        paths = json.loads(evidence_path)
    except (TypeError, ValueError):
        return [evidence_path]
    return paths if isinstance(paths, list) else []


@role_required('admin')
def dashboard_admin():
    """Admin's management dashboard."""
    all_agents = rows_to_dicts(query_db(
        "SELECT * FROM agents ORDER BY verification_status, agency_name"
    ))
    report_history_rows = rows_to_dicts(query_db(
        "SELECT r.*, u.full_name AS worker_name, u.email AS worker_email "
        "FROM reports r "
        "LEFT JOIN users u ON r.worker_id = u.id "
        "WHERE r.agent_id IS NOT NULL "
        "ORDER BY r.created_at DESC"
    ))
    open_reports = rows_to_dicts(query_db(
        "SELECT r.*, a.agency_name FROM reports r "
        "LEFT JOIN agents a ON r.agent_id = a.id "
        "WHERE r.status = 'open' ORDER BY r.created_at DESC"
    ))
    for report in open_reports:
        report['evidence_paths'] = parse_report_evidence_paths(report.get('evidence_path'))

    report_history_by_agent = {}
    open_report_counts = {}
    for report in report_history_rows:
        agent_id = report.get('agent_id')
        if not agent_id:
            continue
        report['evidence_paths'] = parse_report_evidence_paths(report.get('evidence_path'))
        report['evidence_filenames'] = [
            os.path.basename(path) for path in report['evidence_paths']
        ]
        report_history_by_agent.setdefault(agent_id, []).append(report)
        if report.get('status') == 'open':
            open_report_counts[agent_id] = open_report_counts.get(agent_id, 0) + 1

    for agent in all_agents:
        history = report_history_by_agent.get(agent['id'], [])
        open_count = open_report_counts.get(agent['id'], 0)
        if agent['verification_status'] == 'reported':
            status_key = 'flagged'
        elif open_count > 0:
            status_key = 'reported'
        elif agent['verification_status'] == 'verified':
            status_key = 'verified'
        else:
            status_key = 'pending'
        agent['admin_status'] = status_key
        agent['report_history'] = history
        agent['report_count'] = len(history)
        agent['open_report_count'] = open_count

    stats = {
        'total': len(all_agents),
        'verified': sum(1 for a in all_agents if a['admin_status'] == 'verified'),
        'pending': sum(1 for a in all_agents if a['admin_status'] == 'pending'),
        'reported': sum(1 for a in all_agents if a['admin_status'] == 'reported'),
        'flagged': sum(1 for a in all_agents if a['admin_status'] == 'flagged'),
        'open_reports': len(open_reports),
    }

    return render_template(
        'dashboard-admin.html',
        agents=all_agents,
        open_reports=open_reports,
        stats=stats,
    )


@role_required('admin')
def update_agent_status(agent_id):
    """Admin sets an agent's verification status."""
    new_status = request.form.get('status')
    if new_status not in ('verified', 'pending', 'reported'):
        flash('Invalid status value.', 'danger')
        return redirect(url_for('dashboard_admin') + '#agents')

    execute_db(
        "UPDATE agents SET verification_status = ? WHERE id = ?",
        (new_status, agent_id)
    )
    display_status = 'flagged' if new_status == 'reported' else new_status
    flash(f'Agent status updated to {display_status}.', 'success')
    return redirect(url_for('dashboard_admin') + '#agents')


@role_required('admin')
def delete_agent(agent_id):
    """Admin permanently removes an agent record and all associated reports."""
    agent = row_to_dict(query_db("SELECT * FROM agents WHERE id = ?", (agent_id,), one=True))
    if not agent:
        flash('Agent not found.', 'danger')
        return redirect(url_for('dashboard_admin') + '#agents')

    execute_db("DELETE FROM reports WHERE agent_id = ?", (agent_id,))
    execute_db("DELETE FROM enquiries WHERE agent_id = ?", (agent_id,))
    execute_db("DELETE FROM agents WHERE id = ?", (agent_id,))
    flash(f'Agent "{agent["agency_name"]}" has been removed from the platform.', 'success')
    return redirect(url_for('dashboard_admin') + '#agents')


@role_required('admin')
def admin_users():
    """Admin views all registered user accounts."""
    users = rows_to_dicts(query_db(
        "SELECT id, full_name, email, role, created_at FROM users ORDER BY role, created_at DESC"
    ))
    report_counts = {}
    for row in query_db("SELECT worker_id, COUNT(*) as c FROM reports GROUP BY worker_id"):
        report_counts[row['worker_id']] = row['c']

    return render_template('admin_users.html', users=users, report_counts=report_counts)


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
    execute_db(
        "DELETE FROM enquiries WHERE agent_id IN (SELECT id FROM agents WHERE user_id = ?)",
        (user_id,)
    )
    execute_db("DELETE FROM enquiries WHERE worker_id = ?", (user_id,))
    execute_db("DELETE FROM agents WHERE user_id = ?", (user_id,))
    execute_db("DELETE FROM reports WHERE worker_id = ?", (user_id,))
    execute_db("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
    execute_db("DELETE FROM chatbot_logs WHERE user_id = ?", (user_id,))
    execute_db("DELETE FROM users WHERE id = ?", (user_id,))
    flash(f'User "{name}" has been permanently removed.', 'success')
    return redirect(url_for('admin_users'))


@role_required('admin')
def resolve_report(report_id):
    """
    Admin marks a report as resolved or dismissed.
    action=flag    -> also flags the agent as 'reported'
    action=dismiss -> just closes the report
    """
    action = request.form.get('action')

    if action == 'flag':
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

    return redirect(url_for('dashboard_admin') + '#reports')


@role_required('admin')
def report_evidence(report_id, file_index):
    """Serve report evidence to admins without exposing local file paths."""
    report = row_to_dict(query_db(
        "SELECT evidence_path FROM reports WHERE id = ?",
        (report_id,), one=True
    ))
    evidence_paths = parse_report_evidence_paths(report.get('evidence_path') if report else None)
    if file_index < 0 or file_index >= len(evidence_paths):
        abort(404)

    filename = os.path.basename(evidence_paths[file_index])
    return send_from_directory(current_app.config['REPORT_EVIDENCE_FOLDER'], filename)


def register_admin_routes(app):
    """Register admin dashboard and actions with stable endpoints."""
    app.add_url_rule('/dashboard/admin', endpoint='dashboard_admin', view_func=dashboard_admin)
    app.add_url_rule('/admin/agent/<int:agent_id>/status', endpoint='update_agent_status', view_func=update_agent_status, methods=['POST'])
    app.add_url_rule('/admin/agent/<int:agent_id>/delete', endpoint='delete_agent', view_func=delete_agent, methods=['POST'])
    app.add_url_rule('/admin/users', endpoint='admin_users', view_func=admin_users)
    app.add_url_rule('/admin/user/<int:user_id>/delete', endpoint='admin_delete_user', view_func=admin_delete_user, methods=['POST'])
    app.add_url_rule('/admin/report/<int:report_id>/evidence/<int:file_index>', endpoint='report_evidence', view_func=report_evidence)
    app.add_url_rule('/admin/report/<int:report_id>/resolve', endpoint='resolve_report', view_func=resolve_report, methods=['POST'])
