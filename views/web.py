from views.web_auth import login, logout, register
from views.web_dashboards import (
    dashboard,
    dashboard_agent,
    dashboard_worker,
    my_enquiries,
    my_reports,
)
from views.web_enquiries_reports import reply_enquiry, submit_enquiry, submit_report
from views.web_profiles_jobs import (
    agent_worker_profile,
    close_job_listing,
    create_job_listing,
    send_job_interest,
    update_agent_profile,
    update_worker_job_preferences,
    update_worker_profile,
)
from views.web_public import agent_detail, agents, index, migration_guide


def register_web_routes(app):
    """Register public/auth/dashboard/report routes with stable endpoints."""
    routes = (
        ('/', 'index', index, None),
        ('/agents', 'agents', agents, None),
        ('/login', 'login', login, ['GET', 'POST']),
        ('/register', 'register', register, ['GET', 'POST']),
        ('/logout', 'logout', logout, None),
        ('/agents/<int:agent_id>', 'agent_detail', agent_detail, None),
        ('/my-reports', 'my_reports', my_reports, None),
        ('/my-enquiries', 'my_enquiries', my_enquiries, None),
        ('/guide', 'migration_guide', migration_guide, None),
        ('/dashboard', 'dashboard', dashboard, None),
        ('/dashboard/worker', 'dashboard_worker', dashboard_worker, None),
        ('/dashboard/agent', 'dashboard_agent', dashboard_agent, None),
        ('/enquiry', 'submit_enquiry', submit_enquiry, ['GET', 'POST']),
        ('/agent/enquiry/<int:enquiry_id>/reply', 'reply_enquiry', reply_enquiry, ['POST']),
        ('/agent/worker/<int:worker_id>', 'agent_worker_profile', agent_worker_profile, None),
        ('/report', 'submit_report', submit_report, ['GET', 'POST']),
        ('/job/<int:job_id>/interest', 'send_job_interest', send_job_interest, ['POST']),
        ('/worker/profile', 'update_worker_profile', update_worker_profile, ['POST']),
        ('/worker/job-preferences', 'update_worker_job_preferences', update_worker_job_preferences, ['POST']),
        ('/agent/profile', 'update_agent_profile', update_agent_profile, ['POST']),
        ('/agent/job-listings', 'create_job_listing', create_job_listing, ['POST']),
        ('/agent/job/<int:job_id>/close', 'close_job_listing', close_job_listing, ['POST']),
    )

    for rule, endpoint, view_func, methods in routes:
        options = {'methods': methods} if methods else {}
        app.add_url_rule(rule, endpoint=endpoint, view_func=view_func, **options)
