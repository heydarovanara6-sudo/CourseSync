"""
Authentication routes: login / logout / signup for Admins, Teachers, and
Students.

Login is by USERNAME, not email — usernames are unique across the whole
system (checked against both the Users table and the Students table, since
they share one login form). Email is kept only as optional contact info.

Signup is one page (templates/signup.html) with a role switcher — Course
Owner / Teacher / Student — each posting to its own route below:
- Course Owner: /signup — creates a brand new Course with you as its Admin.
- Teacher / Student: /join/teacher or /join/student — pick an existing
  course from the list, then the course's Admin assigns you to the right
  people from their dashboard (existing assign_student / group flows).
"""

from flask import Blueprint, request, redirect, url_for, flash, render_template
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from app.models import User, Student, Course, Role

auth_bp = Blueprint("auth", __name__)


def _dashboard_for(user):
    if user.is_superadmin():
        return url_for("superadmin.dashboard")
    if user.is_admin():
        return url_for("admin.dashboard")
    if user.is_teacher():
        return url_for("teacher.dashboard")
    return url_for("student.dashboard")


def _username_taken(username):
    """Usernames are unique across BOTH the Users and Students tables."""
    return (
        User.query.filter_by(username=username).first() is not None
        or Student.query.filter_by(username=username).first() is not None
    )


@auth_bp.route("/", methods=["GET"])
def index():
    """Redirect the root URL to the right dashboard, or to login."""
    if current_user.is_authenticated:
        return redirect(_dashboard_for(current_user))
    return redirect(url_for("auth.login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    """Anyone can sign up. Signing up creates a new Course with you as its Admin."""
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "GET":
        courses = Course.query.order_by(Course.name).all()
        return render_template("signup.html", default_role="owner", courses=courses)

    course_name = request.form.get("course_name", "").strip()
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower() or None
    password = request.form.get("password", "")

    if not all([course_name, name, username, password]):
        flash("Course name, name, username, and password are all required.", "error")
        return redirect(url_for("auth.signup"))

    if _username_taken(username):
        flash(f'The username "{username}" is already taken. Try another.', "error")
        return redirect(url_for("auth.signup"))

    course = Course(name=course_name)
    db.session.add(course)
    db.session.flush()  # get course.id before creating the owner

    owner = User(name=name, username=username, email=email, role=Role.ADMIN.value, course_id=course.id)
    owner.set_password(password)
    db.session.add(owner)
    db.session.commit()

    login_user(owner)
    flash(f'"{course_name}" is ready — invite your first teacher to get started.', "success")
    return redirect(url_for("admin.dashboard"))


@auth_bp.route("/join/teacher", methods=["GET", "POST"])
def join_teacher():
    """A teacher signs up by picking which existing course they're joining.
    They start out unassigned to any students — the course's Admin assigns
    students to them afterward."""
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    courses = Course.query.order_by(Course.name).all()

    if request.method == "GET":
        return render_template("signup.html", default_role="teacher", courses=courses)

    course_id = request.form.get("course_id", type=int)
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower() or None
    password = request.form.get("password", "")

    course = Course.query.get(course_id)
    if not course or not name or not username or not password:
        flash("Pick a course and fill in every field.", "error")
        return redirect(url_for("auth.join_teacher"))

    if _username_taken(username):
        flash(f'The username "{username}" is already taken. Try another.', "error")
        return redirect(url_for("auth.join_teacher"))

    teacher = User(name=name, username=username, email=email, role=Role.TEACHER.value, course_id=course.id)
    teacher.set_password(password)
    db.session.add(teacher)
    db.session.commit()

    login_user(teacher)
    flash(f"Welcome to {course.name}! Your course admin will assign you students.", "success")
    return redirect(url_for("teacher.dashboard"))


@auth_bp.route("/join/student", methods=["GET", "POST"])
def join_student():
    """A student signs up by picking which existing course they're joining.
    They start out unassigned to any teacher — the course's Admin assigns
    them afterward."""
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    courses = Course.query.order_by(Course.name).all()

    if request.method == "GET":
        return render_template("signup.html", default_role="student", courses=courses)

    course_id = request.form.get("course_id", type=int)
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower() or None
    password = request.form.get("password", "")

    course = Course.query.get(course_id)
    if not course or not name or not username or not password:
        flash("Pick a course and fill in every field.", "error")
        return redirect(url_for("auth.join_student"))

    if _username_taken(username):
        flash(f'The username "{username}" is already taken. Try another.', "error")
        return redirect(url_for("auth.join_student"))

    student = Student(name=name, username=username, email=email, course_id=course.id)
    student.set_password(password)
    db.session.add(student)
    db.session.commit()

    login_user(student)
    flash(f"Welcome to {course.name}! Your course admin will assign you a teacher.", "success")
    return redirect(url_for("student.dashboard"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))

    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")

    account = User.query.filter_by(username=username).first()
    if account is None:
        student = Student.query.filter_by(username=username).first()
        if student and student.has_login():
            account = student

    if account is None or not account.check_password(password):
        flash("That username and password don't match.", "error")
        return redirect(url_for("auth.login"))

    login_user(account)
    return redirect(_dashboard_for(account))


@auth_bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    """Works for any logged-in account — Superadmin, Admin, Teacher, or Student."""
    if request.method == "GET":
        return render_template("change_password.html")

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not current_user.check_password(current_password):
        flash("Your current password is incorrect.", "error")
        return redirect(url_for("auth.change_password"))

    if len(new_password) < 6:
        flash("New password must be at least 6 characters.", "error")
        return redirect(url_for("auth.change_password"))

    if new_password != confirm_password:
        flash("New password and confirmation don't match.", "error")
        return redirect(url_for("auth.change_password"))

    current_user.set_password(new_password)
    db.session.commit()
    flash("Your password has been changed.", "success")
    return redirect(_dashboard_for(current_user))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You've been logged out.", "info")
    return redirect(url_for("auth.login"))