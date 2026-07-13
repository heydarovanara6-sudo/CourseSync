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
from datetime import date, time

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models import (
    User, Student, Role, Cycle, Attendance, Homework, TimetableEntry, Group, GroupSession,
)
from app.routes.auth import _username_taken

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

    # Every in-progress lesson cycle in the course, across every teacher —
    # so the admin can see everyone's 8/10-lesson progress at a glance
    # without clicking into each teacher individually.
    active_cycle_list = (
        Cycle.query.join(Student)
        .filter(Student.course_id == current_user.course_id, Cycle.completed.is_(False))
        .order_by(Cycle.started_on.desc())
        .all()
    )

    return render_template(
        "admin/dashboard.html",
        teachers=teachers,
        students=students,
        active_cycles=len(active_cycle_list),
        active_cycle_list=active_cycle_list,
    )


# ---------------------------------------------------------------------------
# Teachers: create / view / edit / delete
# ---------------------------------------------------------------------------

@admin_bp.route("/teachers", methods=["POST"])
@admin_required
def add_teacher():
    name = request.form.get("name", "").strip()
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower() or None
    password = request.form.get("password", "")

    if not name or not username or not password:
        flash("Name, username, and password are all required.", "error")
        return redirect(url_for("admin.dashboard"))

    if _username_taken(username):
        flash(f'The username "{username}" is already taken.', "error")
        return redirect(url_for("admin.dashboard"))

    teacher = User(name=name, username=username, email=email, role=Role.TEACHER.value, course_id=current_user.course_id)
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
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower() or None
    new_password = request.form.get("password", "").strip()

    if not name or not username:
        flash("Name and username are required.", "error")
        return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))

    username_owner = User.query.filter_by(username=username).first()
    if username_owner and username_owner.id != teacher.id:
        flash(f'The username "{username}" is already taken.', "error")
        return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))
    if Student.query.filter_by(username=username).first():
        flash(f'The username "{username}" is already taken.', "error")
        return redirect(url_for("admin.teacher_detail", teacher_id=teacher.id))

    teacher.name = name
    teacher.username = username
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
    username = request.form.get("username", "").strip().lower() or None
    password = request.form.get("password", "").strip() or None
    email = request.form.get("email", "").strip().lower() or None
    teacher_ids = request.form.getlist("teacher_ids", type=int)

    # Only teachers within THIS course can ever be assigned — even if the
    # form were tampered with to include another course's teacher id.
    teachers = User.query.filter(
        User.id.in_(teacher_ids), User.course_id == current_user.course_id
    ).all()

    if not name or not teachers:
        flash("A name and at least one teacher are required.", "error")
        return redirect(url_for("admin.dashboard"))

    if password and not username:
        flash("Give the student a username so that password can be used to log in.", "error")
        return redirect(url_for("admin.dashboard"))

    if username and _username_taken(username):
        flash(f'The username "{username}" is already taken.', "error")
        return redirect(url_for("admin.dashboard"))

    student = Student(name=name, username=username, email=email, teachers=teachers, course_id=current_user.course_id)
    if password:
        student.set_password(password)
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
    username = request.form.get("username", "").strip().lower() or None
    email = request.form.get("email", "").strip().lower() or None
    new_password = request.form.get("password", "").strip()

    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("admin.student_detail", student_id=student.id))

    if email:
        existing = Student.query.filter(Student.email == email, Student.id != student.id).first()
        if existing:
            flash(f"Another student already uses {email}.", "error")
            return redirect(url_for("admin.student_detail", student_id=student.id))

    if username:
        username_owner = Student.query.filter_by(username=username).first()
        if username_owner and username_owner.id != student.id:
            flash(f'The username "{username}" is already taken.', "error")
            return redirect(url_for("admin.student_detail", student_id=student.id))
        if User.query.filter_by(username=username).first():
            flash(f'The username "{username}" is already taken.', "error")
            return redirect(url_for("admin.student_detail", student_id=student.id))

    student.name = name
    student.username = username
    student.email = email
    if new_password:
        if not username:
            flash("A student needs a username set before they can log in.", "error")
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
# Timetable — admin can view AND manage every teacher's timetable
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

    teachers = _assignable_teachers()
    return render_template("admin/timetable.html", by_teacher=by_teacher, teachers=teachers)


@admin_bp.route("/teachers/<int:teacher_id>/timetable", methods=["POST"])
@admin_required
def add_timetable_entry(teacher_id):
    """Add a timetable slot on behalf of any teacher in this course."""
    teacher = User.query.filter_by(id=teacher_id, course_id=current_user.course_id).first_or_404()

    day_of_week = request.form.get("day_of_week", type=int)
    start_str = request.form.get("start_time", "")
    end_str = request.form.get("end_time", "")
    target_type = request.form.get("target_type", "custom")
    title = request.form.get("title", "").strip() or None

    if day_of_week is None or not (0 <= day_of_week <= 6):
        flash("Pick a valid day of the week.", "error")
        return redirect(url_for("admin.timetable"))

    try:
        start_time = time.fromisoformat(start_str)
        end_time = time.fromisoformat(end_str)
    except ValueError:
        flash("Enter a valid start and end time.", "error")
        return redirect(url_for("admin.timetable"))

    if end_time <= start_time:
        flash("End time must be after start time.", "error")
        return redirect(url_for("admin.timetable"))

    student_id = None
    group_id = None

    if target_type == "student":
        student_id = request.form.get("student_id", type=int)
        student = Student.query.get_or_404(student_id)
        if teacher not in student.teachers:
            flash("That student isn't assigned to this teacher.", "error")
            return redirect(url_for("admin.timetable"))
    elif target_type == "group":
        group_id = request.form.get("group_id", type=int)
        Group.query.filter_by(id=group_id, teacher_id=teacher.id).first_or_404()
    elif not title:
        flash("Give this slot a label, or pick a student/group.", "error")
        return redirect(url_for("admin.timetable"))

    db.session.add(TimetableEntry(
        teacher_id=teacher.id,
        student_id=student_id,
        group_id=group_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        title=title,
    ))
    db.session.commit()
    flash(f"Added to {teacher.name}'s timetable.", "success")
    return redirect(url_for("admin.timetable"))


@admin_bp.route("/timetable/<int:entry_id>/delete", methods=["POST"])
@admin_required
def delete_timetable_entry(entry_id):
    entry = (
        TimetableEntry.query.join(User, TimetableEntry.teacher_id == User.id)
        .filter(TimetableEntry.id == entry_id, User.course_id == current_user.course_id)
        .first_or_404()
    )
    db.session.delete(entry)
    db.session.commit()
    flash("Removed from the timetable.", "success")
    return redirect(url_for("admin.timetable"))


# ---------------------------------------------------------------------------
# Homework — admin can view AND assign/grade homework for any teacher/student
# ---------------------------------------------------------------------------

@admin_bp.route("/homework")
@admin_required
def homework():
    assignments = (
        Homework.query.join(Student, Homework.student_id == Student.id)
        .filter(Student.course_id == current_user.course_id)
        .order_by(Homework.created_at.desc())
        .all()
    )
    teachers = _assignable_teachers()
    students = Student.query.filter_by(course_id=current_user.course_id).order_by(Student.name).all()
    return render_template("admin/homework.html", assignments=assignments, teachers=teachers, students=students)


@admin_bp.route("/homework", methods=["POST"], endpoint="add_homework")
@admin_required
def add_homework():
    teacher_id = request.form.get("teacher_id", type=int)
    student_id = request.form.get("student_id", type=int)
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip() or None
    due_date_str = request.form.get("due_date")

    teacher = User.query.filter_by(id=teacher_id, course_id=current_user.course_id).first_or_404()
    student = Student.query.filter_by(id=student_id, course_id=current_user.course_id).first_or_404()

    if teacher not in student.teachers:
        flash("That student isn't assigned to that teacher.", "error")
        return redirect(url_for("admin.homework"))

    if not title:
        flash("Give the assignment a title.", "error")
        return redirect(url_for("admin.homework"))

    due_date = None
    if due_date_str:
        try:
            due_date = date.fromisoformat(due_date_str)
        except ValueError:
            due_date = None

    db.session.add(Homework(
        teacher_id=teacher.id, student_id=student.id, title=title,
        description=description, due_date=due_date,
    ))
    db.session.commit()
    flash(f'"{title}" assigned to {student.name}.', "success")
    return redirect(url_for("admin.homework"))


@admin_bp.route("/homework/<int:homework_id>")
@admin_required
def homework_detail(homework_id):
    hw = (
        Homework.query.join(Student, Homework.student_id == Student.id)
        .filter(Homework.id == homework_id, Student.course_id == current_user.course_id)
        .first_or_404()
    )
    return render_template("admin/homework_detail.html", homework=hw)


@admin_bp.route("/homework/<int:homework_id>/grade", methods=["POST"])
@admin_required
def grade_homework(homework_id):
    hw = (
        Homework.query.join(Student, Homework.student_id == Student.id)
        .filter(Homework.id == homework_id, Student.course_id == current_user.course_id)
        .first_or_404()
    )
    if hw.submission is None:
        flash("This student hasn't submitted anything yet.", "error")
        return redirect(url_for("admin.homework_detail", homework_id=hw.id))

    from datetime import datetime as _dt
    hw.submission.teacher_feedback = request.form.get("teacher_feedback", "").strip() or None
    hw.submission.grade = request.form.get("grade", "").strip() or None
    hw.submission.graded_at = _dt.utcnow()
    db.session.commit()
    flash("Feedback saved.", "success")
    return redirect(url_for("admin.homework_detail", homework_id=hw.id))


@admin_bp.route("/homework/<int:homework_id>/delete", methods=["POST"])
@admin_required
def delete_homework(homework_id):
    hw = (
        Homework.query.join(Student, Homework.student_id == Student.id)
        .filter(Homework.id == homework_id, Student.course_id == current_user.course_id)
        .first_or_404()
    )
    db.session.delete(hw)
    db.session.commit()
    flash("Assignment deleted.", "success")
    return redirect(url_for("admin.homework"))


# ---------------------------------------------------------------------------
# Groups — admin can view AND manage every group in the course
# ---------------------------------------------------------------------------

@admin_bp.route("/groups")
@admin_required
def groups():
    course_groups = (
        Group.query.join(User, Group.teacher_id == User.id)
        .filter(User.course_id == current_user.course_id)
        .order_by(Group.name)
        .all()
    )
    teachers = _assignable_teachers()
    return render_template("admin/groups.html", groups=course_groups, teachers=teachers)


@admin_bp.route("/groups", methods=["POST"], endpoint="add_group")
@admin_required
def add_group():
    teacher_id = request.form.get("teacher_id", type=int)
    name = request.form.get("name", "").strip()

    teacher = User.query.filter_by(id=teacher_id, course_id=current_user.course_id).first_or_404()

    if not name:
        flash("Give the group a name.", "error")
        return redirect(url_for("admin.groups"))

    db.session.add(Group(name=name, teacher_id=teacher.id))
    db.session.commit()
    flash(f'"{name}" was created for {teacher.name}.', "success")
    return redirect(url_for("admin.groups"))


@admin_bp.route("/groups/<int:group_id>")
@admin_required
def group_detail(group_id):
    group = (
        Group.query.join(User, Group.teacher_id == User.id)
        .filter(Group.id == group_id, User.course_id == current_user.course_id)
        .first_or_404()
    )
    unassigned_students = [s for s in group.teacher.students if group not in s.groups]
    sessions = sorted(group.sessions, key=lambda s: s.session_date, reverse=True)
    return render_template(
        "admin/group_detail.html",
        group=group,
        unassigned_students=unassigned_students,
        sessions=sessions,
        today=date.today().isoformat(),
    )


@admin_bp.route("/groups/<int:group_id>/students", methods=["POST"])
@admin_required
def add_to_group(group_id):
    group = (
        Group.query.join(User, Group.teacher_id == User.id)
        .filter(Group.id == group_id, User.course_id == current_user.course_id)
        .first_or_404()
    )
    student_id = request.form.get("student_id", type=int)
    student = Student.query.filter_by(id=student_id, course_id=current_user.course_id).first_or_404()

    if group.teacher not in student.teachers:
        flash("That student isn't assigned to this group's teacher.", "error")
        return redirect(url_for("admin.group_detail", group_id=group.id))

    if group not in student.groups:
        student.groups.append(group)
        db.session.commit()
        flash(f"{student.name} added to {group.name}.", "success")
    return redirect(url_for("admin.group_detail", group_id=group.id))


@admin_bp.route("/groups/<int:group_id>/sessions", methods=["POST"])
@admin_required
def add_session(group_id):
    group = (
        Group.query.join(User, Group.teacher_id == User.id)
        .filter(Group.id == group_id, User.course_id == current_user.course_id)
        .first_or_404()
    )

    session_date_str = request.form.get("session_date")
    try:
        session_date = date.fromisoformat(session_date_str) if session_date_str else date.today()
    except ValueError:
        session_date = date.today()

    topic = request.form.get("topic", "").strip() or None

    group_session = GroupSession(group_id=group.id, session_date=session_date, topic=topic)
    db.session.add(group_session)
    db.session.flush()

    for student in group.students:
        present = request.form.get(f"present_{student.id}") is not None
        db.session.add(Attendance(session_id=group_session.id, student_id=student.id, present=present))

    db.session.commit()
    flash("Attendance logged.", "success")
    return redirect(url_for("admin.group_detail", group_id=group.id))


@admin_bp.route("/groups/<int:group_id>/delete", methods=["POST"])
@admin_required
def delete_group(group_id):
    group = (
        Group.query.join(User, Group.teacher_id == User.id)
        .filter(Group.id == group_id, User.course_id == current_user.course_id)
        .first_or_404()
    )
    name = group.name
    db.session.delete(group)
    db.session.commit()
    flash(f'"{name}" was deleted.', "success")
    return redirect(url_for("admin.groups"))