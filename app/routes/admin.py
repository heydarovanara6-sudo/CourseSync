"""
Admin routes (Course Owner): create/edit/delete teachers and students,
assign students to one or more teachers, drill into a single teacher's or
student's full record, and view the whole course's timetable.

Everything here is scoped to `current_user.course_id` — a Course Owner
never sees or touches another course's data, even by guessing an ID
(every lookup below filters on course_id, not just the raw primary key).

Note: Admins (course owners) can also act as a teacher themselves — so
"assignable teacher" lists include the admin's own account too.
"""

from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models import User, Student, Role, Cycle, Attendance, Homework, TimetableEntry

admin_bp = Blueprint("admin", __name__)


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin():
            flash("Admin access required.", "error")
            return redirect(url_for("auth.index"))
        return view_func(*args, **kwargs)
    return wrapped


def _assignable_teachers():
    """Teachers AND the admin's own account, scoped to this admin's course."""
    return User.query.filter(
        User.course_id == current_user.course_id,
        User.role.in_([Role.TEACHER.value, Role.ADMIN.value]),
    ).order_by(User.role.desc(), User.name).all()


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    teachers = _assignable_teachers()
    students = Student.query.filter_by(course_id=current_user.course_id).order_by(Student.name).all()
    active_cycles = (
        Cycle.query.join(Student)
        .filter(Student.course_id == current_user.course_id, Cycle.completed.is_(False))
        .count()
    )
    return render_template(
        "admin/dashboard.html",
        teachers=teachers,
        students=students,
        active_cycles=active_cycles,
    )


# ---------------------------------------------------------------------------
# Teachers: create / view / edit / delete
# ---------------------------------------------------------------------------

@admin_bp.route("/teachers", methods=["POST"])
@admin_required
def add_teacher():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not name or not email or not password:
        flash("Name, email, and password are all required.", "error")
        return redirect(url_for("admin.dashboard"))

    if User.query.filter_by(email=email).first():
        flash(f"An account with {email} already exists.", "error")
        return redirect(url_for("admin.dashboard"))

    teacher = User(name=name, email=email, role=Role.TEACHER.value, course_id=current_user.course_id)
    teacher.set_password(password)
    db.session.add(teacher)
    db.session.commit()

    flash(f"{name} was added as a teacher.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/teachers/<int:teacher_id>")
@admin_required
def teacher_detail(teacher_id):
    """Full drill-down view of one teacher: their students, cycles, groups, homework."""
    teacher = User.query.filter_by(id=teacher_id, course_id=current_user.course_id).first_or_404()

    students = teacher.students
    active_cycles = [
        c for s in students for c in s.cycles if not c.completed and c.teacher_id == teacher.id
    ]
    past_cycles = [
        c for s in students for c in s.cycles if c.completed and c.teacher_id == teacher.id
    ]
    groups = teacher.groups
    homework = Homework.query.filter_by(teacher_id=teacher.id).order_by(Homework.created_at.desc()).all()

    return render_template(
        "admin/teacher_detail.html",
        teacher=teacher,
        students=students,
        active_cycles=active_cycles,
        past_cycles=past_cycles,
        groups=groups,
        homework=homework,
    )


@admin_bp.route("/teachers/<int:teacher_id>/edit", methods=["POST"])
@admin_required
def edit_teacher(teacher_id):
    teacher = User.query.filter(
        User.id == teacher_id, User.course_id == current_user.course_id, User.role != Role.ADMIN.value
    ).first_or_404()

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    new_password = request.form.get("password", "").strip()

    if not name or not email:
        flash("Name and email are required.", "error")
        return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))

    existing = User.query.filter(User.email == email, User.id != teacher.id).first()
    if existing:
        flash(f"Another account already uses {email}.", "error")
        return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))

    teacher.name = name
    teacher.email = email
    if new_password:
        teacher.set_password(new_password)

    db.session.commit()
    flash("Teacher details updated.", "success")
    return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))


@admin_bp.route("/teachers/<int:teacher_id>/delete", methods=["POST"])
@admin_required
def delete_teacher(teacher_id):
    teacher = User.query.filter(
        User.id == teacher_id, User.course_id == current_user.course_id, User.role != Role.ADMIN.value
    ).first_or_404()
    name = teacher.name

    db.session.delete(teacher)  # cascades to their groups; cycles/feedback keep teacher_id as history
    db.session.commit()
    flash(f"{name} was deleted.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/teachers/<int:teacher_id>/promote", methods=["POST"])
@admin_required
def promote_teacher(teacher_id):
    """Give a teacher full admin (co-owner) rights over this course."""
    teacher = User.query.filter_by(
        id=teacher_id, course_id=current_user.course_id, role=Role.TEACHER.value
    ).first_or_404()

    teacher.role = Role.ADMIN.value
    db.session.commit()
    flash(f"{teacher.name} is now a course admin.", "success")
    return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))


@admin_bp.route("/teachers/<int:teacher_id>/demote", methods=["POST"])
@admin_required
def demote_admin(teacher_id):
    """Remove another admin's admin rights, turning them back into a regular teacher."""
    target = User.query.filter_by(
        id=teacher_id, course_id=current_user.course_id, role=Role.ADMIN.value
    ).first_or_404()

    remaining_admins = User.query.filter_by(
        course_id=current_user.course_id, role=Role.ADMIN.value
    ).count()
    if remaining_admins <= 1:
        flash("You can't remove the only admin left in this course.", "error")
        return redirect(url_for("admin.teacher_detail", teacher_id=target.id))

    target.role = Role.TEACHER.value
    db.session.commit()
    flash(f"{target.name} is no longer a course admin.", "success")
    return redirect(url_for("admin.teacher_detail", teacher_id=target.id))


# ---------------------------------------------------------------------------
# Students: create / view / edit / delete / assign
# ---------------------------------------------------------------------------

@admin_bp.route("/students", methods=["POST"])
@admin_required
def add_student():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip() or None
    teacher_ids = request.form.getlist("teacher_ids", type=int)

    # Only teachers within THIS course can ever be assigned — even if the
    # form were tampered with to include another course's teacher id.
    teachers = User.query.filter(
        User.id.in_(teacher_ids), User.course_id == current_user.course_id
    ).all()

    if not name or not teachers:
        flash("A name and at least one teacher are required.", "error")
        return redirect(url_for("admin.dashboard"))

    student = Student(name=name, email=email, teachers=teachers, course_id=current_user.course_id)
    db.session.add(student)
    db.session.commit()

    teacher_names = ", ".join(t.name for t in teachers)
    flash(f"{name} was added and assigned to {teacher_names}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/students/<int:student_id>")
@admin_required
def student_detail(student_id):
    """Full drill-down view of one student: teachers, cycles, feedback, attendance, homework."""
    student = Student.query.filter_by(id=student_id, course_id=current_user.course_id).first_or_404()

    cycles = sorted(student.cycles, key=lambda c: c.created_at, reverse=True)
    attendance = (
        Attendance.query.filter_by(student_id=student.id)
        .join(Attendance.session)
        .order_by(db.desc("session_date"))
        .all()
    )
    homework = Homework.query.filter_by(student_id=student.id).order_by(Homework.created_at.desc()).all()
    all_teachers = _assignable_teachers()

    return render_template(
        "admin/student_detail.html",
        student=student,
        cycles=cycles,
        attendance=attendance,
        homework=homework,
        all_teachers=all_teachers,
    )


@admin_bp.route("/students/<int:student_id>/edit", methods=["POST"])
@admin_required
def edit_student(student_id):
    student = Student.query.filter_by(id=student_id, course_id=current_user.course_id).first_or_404()

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip() or None
    new_password = request.form.get("password", "").strip()

    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.student_detail", student_id=student.id))

    if email:
        existing = Student.query.filter(Student.email == email, Student.id != student.id).first()
        if existing:
            flash(f"Another student already uses {email}.", "error")
            return redirect(url_for("admin.student_detail", student_id=student.id))

    student.name = name
    student.email = email
    if new_password:
        if not email:
            flash("A student needs an email set before they can log in.", "error")
            return redirect(url_for("admin.student_detail", student_id=student.id))
        student.set_password(new_password)

    db.session.commit()
    flash("Student details updated.", "success")
    return redirect(url_for("admin.student_detail", student_id=student.id))


@admin_bp.route("/students/<int:student_id>/delete", methods=["POST"])
@admin_required
def delete_student(student_id):
    student = Student.query.filter_by(id=student_id, course_id=current_user.course_id).first_or_404()
    name = student.name

    db.session.delete(student)
    db.session.commit()
    flash(f"{name} was deleted.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.route("/students/<int:student_id>/teachers", methods=["POST"])
@admin_required
def assign_student(student_id):
    """Set the full list of teachers a student is assigned to (replaces the old list)."""
    teacher_ids = request.form.getlist("teacher_ids", type=int)

    student = Student.query.filter_by(id=student_id, course_id=current_user.course_id).first_or_404()
    teachers = User.query.filter(
        User.id.in_(teacher_ids), User.course_id == current_user.course_id
    ).all()

    if not teachers:
        flash("A student needs at least one teacher assigned.", "error")
        return redirect(request.referrer or url_for("admin.dashboard"))

    student.teachers = teachers
    db.session.commit()

    teacher_names = ", ".join(t.name for t in teachers)
    flash(f"{student.name} is now assigned to {teacher_names}.", "success")
    return redirect(request.referrer or url_for("admin.dashboard"))


# ---------------------------------------------------------------------------
# Timetable — admin sees every teacher's timetable in their course (read-only)
# ---------------------------------------------------------------------------

@admin_bp.route("/timetable")
@admin_required
def timetable():
    entries = (
        TimetableEntry.query.join(User, TimetableEntry.teacher_id == User.id)
        .filter(User.course_id == current_user.course_id)
        .order_by(User.name, TimetableEntry.day_of_week, TimetableEntry.start_time)
        .all()
    )
    # Group entries by teacher for a clean per-teacher view
    by_teacher = {}
    for entry in entries:
        by_teacher.setdefault(entry.teacher, []).append(entry)

    return render_template("admin/timetable.html", by_teacher=by_teacher)