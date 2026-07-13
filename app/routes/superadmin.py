"""
Superadmin routes: create Courses (tenants) and their Course Owners.

The Superadmin manages infrastructure only — it does not drill into a
course's teachers/students/cycles/etc. That isolation is the whole point:
each Course Owner runs their own course without seeing (or being seen by)
any other course.
"""

from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models import Course, User, Student, Role
from app.routes.auth import _username_taken

superadmin_bp = Blueprint("superadmin", __name__)


def superadmin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_superadmin():
            flash("Superadmin access required.", "error")
            return redirect(url_for("auth.index"))
        return view_func(*args, **kwargs)
    return wrapped


@superadmin_bp.route("/dashboard")
@superadmin_required
def dashboard():
    courses = Course.query.order_by(Course.name).all()
    return render_template("superadmin/dashboard.html", courses=courses)


@superadmin_bp.route("/courses", methods=["POST"])
@superadmin_required
def add_course():
    name = request.form.get("name", "").strip()
    owner_name = request.form.get("owner_name", "").strip()
    owner_username = request.form.get("owner_username", "").strip().lower()
    owner_email = request.form.get("owner_email", "").strip().lower() or None
    owner_password = request.form.get("owner_password", "")

    if not all([name, owner_name, owner_username, owner_password]):
        flash("Course name and owner details (including a username) are all required.", "error")
        return redirect(url_for("superadmin.dashboard"))

    if _username_taken(owner_username):
        flash(f'The username "{owner_username}" is already taken.', "error")
        return redirect(url_for("superadmin.dashboard"))

    course = Course(name=name)
    db.session.add(course)
    db.session.flush()  # get course.id before creating the owner

    owner = User(name=owner_name, username=owner_username, email=owner_email, role=Role.ADMIN.value, course_id=course.id)
    owner.set_password(owner_password)
    db.session.add(owner)
    db.session.commit()

    flash(f'"{name}" created — {owner_name} can now log in and run it.', "success")
    return redirect(url_for("superadmin.dashboard"))


@superadmin_bp.route("/courses/<int:course_id>/delete", methods=["POST"])
@superadmin_required
def delete_course(course_id):
    course = Course.query.get_or_404(course_id)
    name = course.name

    db.session.delete(course)  # cascades to its users and students (and their data)
    db.session.commit()
    flash(f'"{name}" and everything in it was deleted.', "success")
    return redirect(url_for("superadmin.dashboard"))