"""
Teacher routes: track lesson cycles, manage groups & attendance, assign
homework, and grade submissions.

Note: a student can be assigned to more than one teacher, so every view here
is scoped to "this teacher's relationship with this student" — e.g. a cycle
started by Teacher A never shows up as Teacher B's active cycle for the
same student. Admins can also act as a teacher (per-project decision), so
the access check below allows either role.
"""

from datetime import date, time
from functools import wraps

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from app import db
from app.models import (
    Student, Cycle, Lesson, Feedback, Group, GroupSession, Attendance, Homework,
    TimetableEntry, DAY_NAMES,
)

teacher_bp = Blueprint("teacher", __name__)


def teacher_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not (current_user.is_teacher() or current_user.is_admin()):
            flash("Teacher access required.", "error")
            return redirect(url_for("auth.index"))
        return view_func(*args, **kwargs)
    return wrapped


@teacher_bp.route("/dashboard")
@teacher_required
def dashboard():
    students = current_user.students  # already ordered by name via the relationship
    return render_template("teacher/dashboard.html", students=students)


@teacher_bp.route("/students/<int:student_id>")
@teacher_required
def student_detail(student_id):
    student = Student.query.get_or_404(student_id)
    if current_user not in student.teachers:
        flash("That student isn't assigned to you.", "error")
        return redirect(url_for("teacher.dashboard"))

    active_cycle = student.active_cycle_for(current_user.id)
    past_cycles = student.past_cycles_for(current_user.id)
    homework = Homework.query.filter_by(
        student_id=student.id, teacher_id=current_user.id
    ).order_by(Homework.created_at.desc()).all()

    return render_template(
        "teacher/lesson_tracker.html",
        student=student,
        active_cycle=active_cycle,
        past_cycles=past_cycles,
        homework=homework,
    )


@teacher_bp.route("/students/<int:student_id>/cycles/start", methods=["POST"])
@teacher_required
def start_cycle(student_id):
    """Start a new 8- or 10-lesson cycle for a student (scoped to this teacher)."""
    total_lessons = request.form.get("total_lessons", type=int, default=8)
    if total_lessons not in (8, 10):
        flash("Cycle length must be 8 or 10 lessons.", "error")
        return redirect(url_for("teacher.student_detail", student_id=student_id))

    student = Student.query.get_or_404(student_id)
    if current_user not in student.teachers:
        flash("That student isn't assigned to you.", "error")
        return redirect(url_for("teacher.dashboard"))

    if student.active_cycle_for(current_user.id):
        flash("This student already has an active cycle with you.", "error")
        return redirect(url_for("teacher.student_detail", student_id=student_id))

    cycle = Cycle(student_id=student.id, teacher_id=current_user.id, total_lessons=total_lessons)
    db.session.add(cycle)
    db.session.flush()  # get cycle.id before creating lessons

    for n in range(1, total_lessons + 1):
        db.session.add(Lesson(cycle_id=cycle.id, lesson_number=n))

    db.session.commit()
    flash(f"Started a new {total_lessons}-lesson cycle for {student.name}.", "success")
    return redirect(url_for("teacher.student_detail", student_id=student_id))


@teacher_bp.route("/lessons/<int:lesson_id>/complete", methods=["POST"])
@teacher_required
def complete_lesson(lesson_id):
    """Mark a single lesson complete, with the date it actually happened."""
    lesson = Lesson.query.get_or_404(lesson_id)
    cycle = lesson.cycle
    if cycle.teacher_id != current_user.id:
        flash("That's not your cycle.", "error")
        return redirect(url_for("teacher.dashboard"))

    lesson_date_str = request.form.get("lesson_date", "")
    try:
        lesson_date = date.fromisoformat(lesson_date_str)
    except ValueError:
        flash("Enter a valid date for this lesson.", "error")
        return redirect(url_for("teacher.student_detail", student_id=cycle.student_id))

    lesson.scheduled_date = lesson_date
    lesson.mark_complete()
    db.session.commit()

    flash(f"Lesson {lesson.lesson_number} stamped for {lesson_date.strftime('%b %d, %Y')}.", "success")
    return redirect(url_for("teacher.student_detail", student_id=cycle.student_id))


@teacher_bp.route("/cycles/<int:cycle_id>/feedback", methods=["POST"])
@teacher_required
def submit_feedback(cycle_id):
    """Write feedback and close out a cycle once all lessons are done."""
    content = request.form.get("content", "").strip()
    cycle = Cycle.query.get_or_404(cycle_id)

    if cycle.teacher_id != current_user.id:
        flash("That's not your cycle.", "error")
        return redirect(url_for("teacher.dashboard"))
    if not content:
        flash("Feedback can't be empty.", "error")
        return redirect(url_for("teacher.student_detail", student_id=cycle.student_id))
    if not cycle.is_ready_to_complete():
        flash("This cycle isn't finished yet.", "error")
        return redirect(url_for("teacher.student_detail", student_id=cycle.student_id))
    if cycle.feedback is not None:
        flash("Feedback was already submitted for this cycle.", "error")
        return redirect(url_for("teacher.student_detail", student_id=cycle.student_id))

    feedback = Feedback(
        cycle_id=cycle.id,
        teacher_id=current_user.id,
        student_id=cycle.student_id,
        content=content,
    )
    cycle.mark_completed()
    db.session.add(feedback)
    db.session.commit()

    flash("Feedback submitted and the cycle is closed.", "success")
    return redirect(url_for("teacher.student_detail", student_id=cycle.student_id))


# ---------------------------------------------------------------------------
# Groups & attendance
# ---------------------------------------------------------------------------

@teacher_bp.route("/groups")
@teacher_required
def groups():
    teacher_groups = Group.query.filter_by(teacher_id=current_user.id).order_by(Group.name).all()
    return render_template("teacher/groups.html", groups=teacher_groups)


@teacher_bp.route("/groups", methods=["POST"], endpoint="add_group")
@teacher_required
def add_group():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Give the group a name.", "error")
        return redirect(url_for("teacher.groups"))

    group = Group(name=name, teacher_id=current_user.id)
    db.session.add(group)
    db.session.commit()
    flash(f'"{name}" was created.', "success")
    return redirect(url_for("teacher.groups"))


@teacher_bp.route("/groups/<int:group_id>")
@teacher_required
def group_detail(group_id):
    group = Group.query.filter_by(id=group_id, teacher_id=current_user.id).first_or_404()
    # Any student assigned to this teacher who isn't already in this specific group
    unassigned_students = [s for s in current_user.students if group not in s.groups]
    sessions = sorted(group.sessions, key=lambda s: s.session_date, reverse=True)
    return render_template(
        "teacher/group_detail.html",
        group=group,
        unassigned_students=unassigned_students,
        sessions=sessions,
        today=date.today().isoformat(),
    )


@teacher_bp.route("/groups/<int:group_id>/students", methods=["POST"])
@teacher_required
def add_to_group(group_id):
    group = Group.query.filter_by(id=group_id, teacher_id=current_user.id).first_or_404()
    student_id = request.form.get("student_id", type=int)
    student = Student.query.get_or_404(student_id)

    if current_user not in student.teachers:
        flash("That student isn't assigned to you.", "error")
        return redirect(url_for("teacher.group_detail", group_id=group.id))

    if group not in student.groups:
        student.groups.append(group)
        db.session.commit()
        flash(f"{student.name} added to {group.name}.", "success")
    return redirect(url_for("teacher.group_detail", group_id=group.id))


@teacher_bp.route("/groups/<int:group_id>/sessions", methods=["POST"])
@teacher_required
def add_session(group_id):
    group = Group.query.filter_by(id=group_id, teacher_id=current_user.id).first_or_404()

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
    return redirect(url_for("teacher.group_detail", group_id=group.id))


# ---------------------------------------------------------------------------
# Homework & submissions
# ---------------------------------------------------------------------------

@teacher_bp.route("/homework")
@teacher_required
def homework_list():
    assignments = Homework.query.filter_by(teacher_id=current_user.id) \
        .order_by(Homework.created_at.desc()).all()
    return render_template(
        "teacher/homework.html", assignments=assignments, students=current_user.students
    )


@teacher_bp.route("/homework", methods=["POST"], endpoint="add_homework")
@teacher_required
def add_homework():
    student_id = request.form.get("student_id", type=int)
    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip() or None
    due_date_str = request.form.get("due_date")

    student = Student.query.get_or_404(student_id)
    if current_user not in student.teachers:
        flash("That student isn't assigned to you.", "error")
        return redirect(url_for("teacher.homework_list"))

    if not title:
        flash("Give the assignment a title.", "error")
        return redirect(url_for("teacher.homework_list"))

    due_date = None
    if due_date_str:
        try:
            due_date = date.fromisoformat(due_date_str)
        except ValueError:
            due_date = None

    homework = Homework(
        teacher_id=current_user.id,
        student_id=student.id,
        title=title,
        description=description,
        due_date=due_date,
    )
    db.session.add(homework)
    db.session.commit()

    flash(f'"{title}" assigned to {student.name}.', "success")
    return redirect(url_for("teacher.homework_list"))


@teacher_bp.route("/homework/<int:homework_id>")
@teacher_required
def homework_detail(homework_id):
    homework = Homework.query.get_or_404(homework_id)
    if homework.teacher_id != current_user.id:
        flash("That assignment isn't yours.", "error")
        return redirect(url_for("teacher.homework_list"))
    return render_template("teacher/homework_detail.html", homework=homework)


@teacher_bp.route("/homework/<int:homework_id>/grade", methods=["POST"])
@teacher_required
def grade_homework(homework_id):
    homework = Homework.query.get_or_404(homework_id)
    if homework.teacher_id != current_user.id:
        flash("That assignment isn't yours.", "error")
        return redirect(url_for("teacher.homework_list"))

    if homework.submission is None:
        flash("This student hasn't submitted anything yet.", "error")
        return redirect(url_for("teacher.homework_detail", homework_id=homework.id))

    from datetime import datetime as _dt
    homework.submission.teacher_feedback = request.form.get("teacher_feedback", "").strip() or None
    homework.submission.grade = request.form.get("grade", "").strip() or None
    homework.submission.graded_at = _dt.utcnow()
    db.session.commit()

    flash("Feedback saved.", "success")
    return redirect(url_for("teacher.homework_detail", homework_id=homework.id))


# ---------------------------------------------------------------------------
# Timetable — each teacher sees and manages only their own
# ---------------------------------------------------------------------------

@teacher_bp.route("/timetable")
@teacher_required
def timetable():
    entries = TimetableEntry.query.filter_by(teacher_id=current_user.id) \
        .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time).all()
    by_day = {i: [] for i in range(7)}
    for entry in entries:
        by_day[entry.day_of_week].append(entry)

    return render_template(
        "teacher/timetable.html",
        by_day=by_day,
        day_names=DAY_NAMES,
        students=current_user.students,
        groups=current_user.groups,
    )


@teacher_bp.route("/timetable", methods=["POST"], endpoint="add_timetable_entry")
@teacher_required
def add_timetable_entry():
    day_of_week = request.form.get("day_of_week", type=int)
    start_str = request.form.get("start_time", "")
    end_str = request.form.get("end_time", "")
    target_type = request.form.get("target_type", "custom")
    title = request.form.get("title", "").strip() or None

    if day_of_week is None or not (0 <= day_of_week <= 6):
        flash("Pick a valid day of the week.", "error")
        return redirect(url_for("teacher.timetable"))

    try:
        start_time = time.fromisoformat(start_str)
        end_time = time.fromisoformat(end_str)
    except ValueError:
        flash("Enter a valid start and end time.", "error")
        return redirect(url_for("teacher.timetable"))

    if end_time <= start_time:
        flash("End time must be after start time.", "error")
        return redirect(url_for("teacher.timetable"))

    student_id = None
    group_id = None

    if target_type == "student":
        student_id = request.form.get("student_id", type=int)
        student = Student.query.get_or_404(student_id)
        if current_user not in student.teachers:
            flash("That student isn't assigned to you.", "error")
            return redirect(url_for("teacher.timetable"))
    elif target_type == "group":
        group_id = request.form.get("group_id", type=int)
        group = Group.query.filter_by(id=group_id, teacher_id=current_user.id).first_or_404()
    elif not title:
        flash("Give this slot a label, or pick a student/group.", "error")
        return redirect(url_for("teacher.timetable"))

    db.session.add(TimetableEntry(
        teacher_id=current_user.id,
        student_id=student_id,
        group_id=group_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        title=title,
    ))
    db.session.commit()
    flash("Added to your timetable.", "success")
    return redirect(url_for("teacher.timetable"))


@teacher_bp.route("/timetable/<int:entry_id>/delete", methods=["POST"])
@teacher_required
def delete_timetable_entry(entry_id):
    entry = TimetableEntry.query.get_or_404(entry_id)
    if entry.teacher_id != current_user.id:
        flash("That's not your timetable entry.", "error")
        return redirect(url_for("teacher.timetable"))

    db.session.delete(entry)
    db.session.commit()
    flash("Removed from your timetable.", "success")
    return redirect(url_for("teacher.timetable"))
