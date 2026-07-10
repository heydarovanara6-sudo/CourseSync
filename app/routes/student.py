"""
Student routes: view your own cycle progress and homework, and submit work.

Students are read-only everywhere except submitting/re-submitting homework —
they can't edit cycles, attendance, or feedback; that stays teacher/admin-only.
"""

from functools import wraps
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models import Homework, Submission, TimetableEntry, DAY_NAMES

student_bp = Blueprint("student", __name__)


def student_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_student():
            flash("Student access required.", "error")
            return redirect(url_for("auth.index"))
        return view_func(*args, **kwargs)
    return wrapped


@student_bp.route("/dashboard")
@student_required
def dashboard():
    homework = Homework.query.filter_by(student_id=current_user.id) \
        .order_by(Homework.created_at.desc()).all()
    return render_template("student/dashboard.html", student=current_user, homework=homework)


@student_bp.route("/homework/<int:homework_id>")
@student_required
def homework_detail(homework_id):
    homework = Homework.query.get_or_404(homework_id)
    if homework.student_id != current_user.id:
        flash("That assignment isn't yours.", "error")
        return redirect(url_for("student.dashboard"))
    return render_template("student/homework_detail.html", homework=homework)


@student_bp.route("/homework/<int:homework_id>/submit", methods=["POST"])
@student_required
def submit_homework(homework_id):
    homework = Homework.query.get_or_404(homework_id)
    if homework.student_id != current_user.id:
        flash("That assignment isn't yours.", "error")
        return redirect(url_for("student.dashboard"))

    content = request.form.get("content", "").strip()
    link = request.form.get("link", "").strip() or None

    if not content:
        flash("Add some text describing your work before submitting.", "error")
        return redirect(url_for("student.homework_detail", homework_id=homework.id))

    if homework.submission:
        # Re-submitting clears any prior grade/feedback since the work has changed.
        homework.submission.content = content
        homework.submission.link = link
        homework.submission.submitted_at = datetime.utcnow()
        homework.submission.teacher_feedback = None
        homework.submission.grade = None
        homework.submission.graded_at = None
    else:
        db.session.add(Submission(
            homework_id=homework.id,
            student_id=current_user.id,
            content=content,
            link=link,
        ))

    db.session.commit()
    flash("Submitted! Your teacher will leave feedback here once they've reviewed it.", "success")
    return redirect(url_for("student.homework_detail", homework_id=homework.id))


@student_bp.route("/timetable")
@student_required
def timetable():
    group_ids = [g.id for g in current_user.groups]

    entries = TimetableEntry.query.filter(
        db.or_(
            TimetableEntry.student_id == current_user.id,
            TimetableEntry.group_id.in_(group_ids) if group_ids else False,
        )
    ).order_by(TimetableEntry.day_of_week, TimetableEntry.start_time).all()

    by_day = {i: [] for i in range(7)}
    for entry in entries:
        by_day[entry.day_of_week].append(entry)

    return render_template("student/timetable.html", by_day=by_day, day_names=DAY_NAMES)
