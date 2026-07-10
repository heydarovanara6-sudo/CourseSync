"""
One-time helper to create the first Superadmin account.

The Superadmin doesn't belong to any course — its only job is creating
Courses and their owners from the Superadmin dashboard after logging in.
Each Course Owner then runs their own course entirely independently.

Usage:
    python seed.py
"""

from app import create_app, db
from app.models import User, Role

app = create_app()

with app.app_context():
    existing = User.query.filter_by(role=Role.SUPERADMIN.value).first()
    if existing:
        print(f"A superadmin already exists: {existing.email}")
    else:
        email = input("Superadmin email: ").strip().lower()
        name = input("Superadmin name: ").strip()
        password = input("Superadmin password: ").strip()

        superadmin = User(name=name, email=email, role=Role.SUPERADMIN.value, course_id=None)
        superadmin.set_password(password)
        db.session.add(superadmin)
        db.session.commit()
        print(f"Superadmin account created for {email}.")
        print("Log in, then create your first course from the Courses page.")
