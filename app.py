"""
app.py
Thin entrypoint for the MigrantSafe Flask application.

Run with:
    python app.py
"""

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
PROJECT_VENV_PYTHON = APP_DIR / '.venv' / 'Scripts' / 'python.exe'


def bootstrap_project_python():
    """Relaunch with the project's virtualenv when app.py is run directly."""
    if not PROJECT_VENV_PYTHON.exists():
        return

    current_python = os.path.normcase(str(Path(sys.executable).resolve()))
    project_python = os.path.normcase(str(PROJECT_VENV_PYTHON.resolve()))
    if current_python == project_python:
        return

    os.execv(
        str(PROJECT_VENV_PYTHON),
        [str(PROJECT_VENV_PYTHON), str(APP_DIR / 'app.py'), *sys.argv[1:]],
    )


if __name__ == '__main__':
    bootstrap_project_python()

from app_factory import create_app
from config import Config


app = create_app()


if __name__ == '__main__':
    app.run(debug=Config.DEBUG, port=5000)
