from flask import flash, redirect, render_template, request, session, url_for

from auth_utils import role_required
from db import execute_db, query_db, row_to_dict, rows_to_dicts


@role_required('admin')
def dashboard_admin():
    """Admin's management dashboard."""
    all_agents = rows_to_dicts(query_db(
        "SELECT * FROM agents ORDER BY verification_status, agency_name"
    ))
    open_reports = rows_to_dicts(query_db(
        "SELECT r.*, a.agency_name FROM reports r "
        "LEFT JOIN agents a ON r.agent_id = a.id "
        "WHERE r.status = 'open' ORDER BY r.created_at DESC"
    ))

    stats = {
        'total': len(all_agents),
        'verified': sum(1 for a in all_agents if a['verification_status'] == 'verified'),
        'pending': sum(1 for a in all_agents if a['verification_status'] == 'pending'),
        'reported': sum(1 for a in all_agents if a['verification_status'] == 'reported'),
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
        return redirect(url_for('dashboard_admin'))

    execute_db(
        "UPDATE agents SET verification_status = ? WHERE id = ?",
        (new_status, agent_id)
    )
    flash(f'Agent status updated to {new_status}.', 'success')
    return redirect(url_for('dashboard_admin'))


@role_required('admin')
def delete_agent(agent_id):
    """Admin permanently removes an agent record and all associated reports."""
    agent = row_to_dict(query_db("SELECT * FROM agents WHERE id = ?", (agent_id,), one=True))
    if not agent:
        flash('Agent not found.', 'danger')
        return redirect(url_for('dashboard_admin'))

    execute_db("DELETE FROM reports WHERE agent_id = ?", (agent_id,))
    execute_db("DELETE FROM enquiries WHERE agent_id = ?", (agent_id,))
    execute_db("DELETE FROM agents WHERE id = ?", (agent_id,))
    flash(f'Agent "{agent["agency_name"]}" has been removed from the platform.', 'success')
    return redirect(url_for('dashboard_admin'))


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

    return redirect(url_for('dashboard_admin'))


def register_admin_routes(app):
    """Register admin dashboard and actions with stable endpoints."""
    app.add_url_rule('/dashboard/admin', endpoint='dashboard_admin', view_func=dashboard_admin)
    app.add_url_rule('/admin/agent/<int:agent_id>/status', endpoint='update_agent_status', view_func=update_agent_status, methods=['POST'])
    app.add_url_rule('/admin/agent/<int:agent_id>/delete', endpoint='delete_agent', view_func=delete_agent, methods=['POST'])
    app.add_url_rule('/admin/users', endpoint='admin_users', view_func=admin_users)
    app.add_url_rule('/admin/user/<int:user_id>/delete', endpoint='admin_delete_user', view_func=admin_delete_user, methods=['POST'])
    app.add_url_rule('/admin/report/<int:report_id>/resolve', endpoint='resolve_report', view_func=resolve_report, methods=['POST'])
