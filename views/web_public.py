from flask import flash, redirect, render_template, request, session, url_for

from db import query_db, row_to_dict, rows_to_dicts
from views.web_shared import VALID_AGENT_STATUSES, is_mobile_request


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

    if status in VALID_AGENT_STATUSES:
        sql += " AND verification_status = ?"
        params.append(status)

    sql += " ORDER BY verification_status ASC, agency_name ASC"

    all_agents = rows_to_dicts(query_db(sql, params))
    all_for_stats = query_db("SELECT verification_status FROM agents")
    stats = {
        'total': len(all_for_stats),
        **{
            agent_status: sum(
                1 for agent in all_for_stats
                if agent['verification_status'] == agent_status
            )
            for agent_status in VALID_AGENT_STATUSES
        },
    }

    return render_template(
        'agents.html',
        agents=all_agents,
        stats=stats,
        q=q,
        status_filter=status,
    )


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


def migration_guide():
    """Step-by-step migration process guide."""
    if is_mobile_request():
        return redirect(url_for('dashboard' if 'user_id' in session else 'index'))

    return render_template('guide.html')
