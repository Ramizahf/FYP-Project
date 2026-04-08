# MigrantSafe

MigrantSafe is a Flask-based web application designed to help migrant workers in Malaysia stay informed and protected.

The platform allows users to:

- verify recruitment agents
- report unethical or suspicious agents
- learn about recruitment fees, visas, and required documents
- understand migrant worker rights
- use a multilingual chatbot in English, Bahasa Melayu, and Bangla

## Features

- Worker, agent, and admin roles
- User registration and login
- Public agent directory
- Agent reporting workflow
- Role-based dashboards
- Multilingual chatbot
- SQLite database for simple local development

## Tech Stack

- Python
- Flask
- SQLite
- Jinja2
- HTML/CSS/JavaScript

## Project Structure

```text
migrantsafe_v6/
|-- app.py
|-- app_factory.py
|-- auth_utils.py
|-- db.py
|-- config.py
|-- init_db.py
|-- requirements.txt
|-- templates/
`-- views/
    |-- __init__.py
    |-- web.py
    |-- admin.py
    `-- chatbot.py
```

## Getting Started

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd <your-repo-folder>/migrantsafe_v6
```

### 2. Create and activate a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root:

```env
OPENCODE_API_KEY=your-api-key-here
OPENCODE_API_BASE_URL=https://openrouter.ai/api/v1
OPENCODE_MODEL=openai/gpt-oss-120b:free
SECRET_KEY=change-this-in-production
FLASK_DEBUG=True
```

Important:

- never commit your real `.env`
- never commit real API keys
- rotate any key that has been exposed publicly

### 5. Initialize the database

```bash
python init_db.py
```

### 6. Run the app

```bash
python app.py
```

Then open:

`http://127.0.0.1:5000`

## Demo Accounts

If you initialize the database with `init_db.py`, these demo accounts are created:

- Worker: `worker@migrantsafe.com` / `Worker01`
- Agent: `agent@migrantsafe.com` / `Agent01`
- Admin: `admin@migrantsafe.com` / `Admin01`

## Chatbot

The chatbot supports:

- English
- Bahasa Melayu
- Bangla

Behavior:

- uses the configured API model when the live service is available
- can return local fallback guidance for supported support topics
- stores conversation logs in the database

## Development Notes

- `app.py` is a thin entrypoint
- `app_factory.py` creates and configures the Flask app
- shared auth and database helpers are split into separate modules
- route logic is modularized under `views/`

## Security Notes

- add `.env` to `.gitignore`
- never commit secrets
- use `.env.example` with placeholders if you want to share config format


