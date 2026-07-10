"""
Authentication routes: login / logout for Admins, Teachers, and Students.

Admins and Teachers live in the `users` table; Students have their own table
with their own optional login (see models.Student.has_login()). Both share
this one login form — we just look in both tables for a matching email.
"""

from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import login_user, logout_user, login_required, current_user

from app.models import User, Student

auth_bp = Blueprint("auth", __name__)


def _dashboard_for(user):
    if user.is_superadmin():
        return url_for("superadmin.dashboard")
    if user.is_admin():
        return url_for("admin.dashboard")
    if user.is_teacher():
        return url_for("teacher.dashboard")
    return url_for("student.dashboard")


@auth_bp.route("/", methods=["GET"])
def index():
    """Redirect the root URL to the right dashboard, or to login."""
    if current_user.is_authenticated:
        return redirect(_dashboard_for(current_user))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    account = User.query.filter_by(email=email).first()
    if account is None:
        student = Student.query.filter(Student.email.ilike(email)).first()
        if student and student.has_login():
            account = student

    if account is None or not account.check_password(password):
        flash("That email and password don't match.", "error")
        return redirect(url_for("auth.login"))

    login_user(account)
    return redirect(_dashboard_for(account))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("auth.login"))
