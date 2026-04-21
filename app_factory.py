import os

from dotenv import load_dotenv
from flask import Flask

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'), override=True)

from auth_utils import init_auth
from config import Config
from db import init_db
from views.admin import register_admin_routes
from views.chatbot import register_chatbot_routes
from views.web import register_web_routes


def register_google_oauth(app):
    """Attach the Google OAuth blueprint when credentials are configured."""
    app.config['GOOGLE_OAUTH_READY'] = False
    app.config['GOOGLE_OAUTH_DISABLED_REASON'] = None

    if not app.config.get('GOOGLE_OAUTH_ENABLED'):
        app.config['GOOGLE_OAUTH_DISABLED_REASON'] = 'missing_config'
        return

    try:
        from flask_dance.contrib.google import make_google_blueprint
    except ImportError:
        app.config['GOOGLE_OAUTH_DISABLED_REASON'] = 'missing_dependency'
        app.logger.warning(
            'Flask-Dance is not installed. Google OAuth is disabled until the dependency is added.'
        )
        return

    if app.config.get('DEBUG'):
        os.environ.setdefault('OAUTHLIB_INSECURE_TRANSPORT', '1')

    os.environ.setdefault('OAUTHLIB_RELAX_TOKEN_SCOPE', '1')

    google_bp = make_google_blueprint(
        client_id=app.config['GOOGLE_OAUTH_CLIENT_ID'],
        client_secret=app.config['GOOGLE_OAUTH_CLIENT_SECRET'],
        scope=app.config['GOOGLE_OAUTH_SCOPES'],
        redirect_to='google_oauth_callback',
        offline=False,
        reprompt_consent=False,
        reprompt_select_account=True,
    )
    app.register_blueprint(google_bp, url_prefix='/auth')
    app.config['GOOGLE_OAUTH_READY'] = True


def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(Config)

    init_db(app)
    init_auth(app)
    register_google_oauth(app)
    register_web_routes(app)
    register_admin_routes(app)
    register_chatbot_routes(app)

    return app
