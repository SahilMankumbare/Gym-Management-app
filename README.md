# gymbroch - Gym Management System

gymbroch is a full-stack gym management web application built with Flask and SQLite. It lets a gym owner register members, track subscription cycles and expiry alerts, collect and analyse monthly revenue, manage trainers, and mark daily trainer attendance. It also provides one-click CSV and Excel report exports, and direct WhatsApp messaging to members using their +91 numbers. The dashboard gives live analytics on active members, expiring subscriptions, plan distribution and revenue growth.

Tech stack: Python (Flask 3.1) as the backend framework, SQLite for storage (auto-created database file), Jinja2 server-side templating, and custom HTML/CSS with SVG icons and vanilla JavaScript for a fully responsive dark theme interface. No heavy frontend framework is required - the app is served as a single deployable folder.

Login: username Admin, password gymbroch@9353.

## Run locally

```
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

## Deploy on PythonAnywhere

Upload all files into /home/YOUR_USERNAME/gymbroch, run `pip install -r requirements.txt`, then point the WSGI configuration file to `wsgi.py` (set the PROJECT_DIR path inside it) and reload the web app.