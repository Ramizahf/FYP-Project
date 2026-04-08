"""
app.py
Thin entrypoint for the MigrantSafe Flask application.

Run with:
    python app.py
"""

from app_factory import create_app
from config import Config


app = create_app()


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=5000)
