"""
Wipes EVERY course, user (admin/teacher/superadmin), student, and all their
data (cycles, homework, attendance, timetable, everything) and leaves a
completely empty database with fresh tables.

This is destructive and cannot be undone. Use it to reset a test/staging
deployment before going live for real.

Usage:
    python reset_db.py
"""

from app import create_app, db

app = create_app()

with app.app_context():
    confirm = input(
        "This will PERMANENTLY delete every course, user, and student in "
        "this database. Type 'yes' to continue: "
    ).strip().lower()

    if confirm != "yes":
        print("Cancelled. Nothing was deleted.")
    else:
        db.drop_all()
        db.create_all()
        print("Database wiped and fresh tables created.")
        print("Run `python seed.py` next to create your Superadmin account.")