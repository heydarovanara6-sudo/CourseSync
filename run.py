"""
CourseSync entry point.

Usage:
    python run.py

Environment variables (all optional, see .env.example):
    SECRET_KEY   - Flask session signing key (set a real one in production)
    DATABASE_URL - SQLAlchemy database URI (defaults to local SQLite)
    FLASK_DEBUG  - "1" to enable debug/reload (defaults off)
    PORT         - port to listen on (defaults to 5000)
"""

import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug, host="127.0.0.1", port=port)
