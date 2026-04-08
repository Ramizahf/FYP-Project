import os

from dotenv import load_dotenv
from flask import Flask

from auth_utils import init_auth
from config import Config
from db import init_db
from views.admin import register_admin_routes
from views.chatbot import register_chatbot_routes
from views.web import register_web_routes


def create_app():
    """Create and configure the Flask application."""
    load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

    app = Flask(__name__)
    app.config.from_object(Config)

    init_db(app)
    init_auth(app)
    register_web_routes(app)
    register_admin_routes(app)
    register_chatbot_routes(app)

    return app
