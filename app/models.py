"""
CourseSync database models.

Core entities:
- Course      : A tenant/organization. Everything below belongs to exactly
                one Course, and Courses never see each other's data. Created
                by the Superadmin; run day-to-day by its Course Owner (an
                Admin scoped to that course).
- User        : Superadmins, Admins (course owners), and Teachers — one
                table, differentiated by `role`. Superadmin has no course;
                everyone else belongs to exactly one.
- Student     : Learners with their own login. A student can be assigned to
                MULTIPLE teachers and can belong to MULTIPLE groups, but
                always within a single Course.
- Group       : A collection of students taught together by one Teacher
- Cycle       : A payment cycle of 8 or 10 lessons for a single student,
                run by one specific teacher
- Lesson      : One individual lesson within a Cycle (tracks completion)
- GroupSession: One group class occurrence (date/topic) for a Group
- Attendance  : Per-student attendance record for a GroupSession
- Feedback    : Teacher's written feedback, produced when a Cycle completes
- Homework    : Material a teacher assigns to one student
- Submission  : A student's response to a Homework assignment
- TimetableEntry: A recurring weekly time slot for a teacher (with a
                student, a group, or just a custom label)
"""

from datetime import datetime, date
from enum import Enum

from flask_login import UserMixin
from sqlalchemy import CheckConstraint
from werkzeug.security import generate_password_hash, check_password_hash

from app import db


# ---------------------------------------------------------------------------
# Enums (stored as plain strings in SQLite for simplicity/portability)
# ---------------------------------------------------------------------------

class Role(str, Enum):
    SUPERADMIN = "superadmin"  # manages Courses; not scoped to any one course
    ADMIN = "admin"            # a Course Owner — full control of their own course
    TEACHER = "teacher"


# ---------------------------------------------------------------------------
# Course (tenant) — everything else belongs to exactly one Course
# ---------------------------------------------------------------------------

class Course(db.Model):
    __tablename__ = "courses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Deleting a Course deletes every User (owner/teachers) and Student in it,
    # which in turn cascades to their groups, cycles, homework, etc.
    users = db.relationship(
        "User", backref="course", cascade="all, delete-orphan",
        foreign_keys="User.course_id",
    )
    students = db.relationship(
        "Student", backref="course", cascade="all, delete-orphan",
        foreign_keys="Student.course_id",
    )

    def owner(self):
        """The Course Owner (Admin) for this course, if one exists."""
        return next((u for u in self.users if u.role == Role.ADMIN.value), None)

    def teacher_count(self) -> int:
        return sum(1 for u in self.users if u.role in (Role.ADMIN.value, Role.TEACHER.value))

    def __repr__(self):
        return f"<Course {self.name}>"


# ---------------------------------------------------------------------------
# Association tables (many-to-many, no extra columns needed)
# ---------------------------------------------------------------------------

student_teachers = db.Table(
    "student_teachers",
    db.Column("student_id", db.Integer, db.ForeignKey("students.id"), primary_key=True),
    db.Column("teacher_id", db.Integer, db.ForeignKey("users.id"), primary_key=True),
)

student_groups = db.Table(
    "student_groups",
    db.Column("student_id", db.Integer, db.ForeignKey("students.id"), primary_key=True),
    db.Column("group_id", db.Integer, db.ForeignKey("groups.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# User (Admin / Teacher)
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=Role.TEACHER.value)
    is_active_flag = db.Column("is_active", db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Every Admin/Teacher belongs to exactly one Course. Superadmins have none
    # (course_id is NULL) — they manage Courses themselves, not day-to-day data.
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=True)

    # A teacher's students/groups (only populated when role == teacher/admin).
    # A student can have several teachers, and a teacher can have several students.
    students = db.relationship(
        "Student", secondary=student_teachers, back_populates="teachers",
        order_by="Student.name",
    )
    groups = db.relationship(
        "Group", back_populates="teacher", foreign_keys="Group.teacher_id"
    )

    __table_args__ = (
        CheckConstraint(
            role.in_([Role.SUPERADMIN.value, Role.ADMIN.value, Role.TEACHER.value]),
            name="ck_users_role",
        ),
    )

    # --- password helpers ---------------------------------------------------
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # Flask-Login uses this to decide whether the account can log in
    @property
    def is_active(self):
        return self.is_active_flag

    def is_superadmin(self) -> bool:
        return self.role == Role.SUPERADMIN.value

    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value

    def is_teacher(self) -> bool:
        return self.role == Role.TEACHER.value

    def is_student(self) -> bool:
        return False

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher = db.relationship("User", back_populates="groups", foreign_keys=[teacher_id])
    students = db.relationship(
        "Student", secondary=student_groups, back_populates="groups",
        order_by="Student.name",
    )
    sessions = db.relationship(
        "GroupSession", back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Group {self.name}>"


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------

class Student(UserMixin, db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)

    # Every student belongs to exactly one Course.
    course_id = db.Column(db.Integer, db.ForeignKey("courses.id"), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # A student can be assigned to several teachers, and can sit in several groups.
    teachers = db.relationship(
        "User", secondary=student_teachers, back_populates="students",
        order_by="User.name",
    )
    groups = db.relationship(
        "Group", secondary=student_groups, back_populates="students",
        order_by="Group.name",
    )

    cycles = db.relationship(
        "Cycle", back_populates="student", cascade="all, delete-orphan",
        order_by="Cycle.created_at.desc()",
    )
    attendance_records = db.relationship(
        "Attendance", back_populates="student", cascade="all, delete-orphan"
    )
    homework_assignments = db.relationship(
        "Homework", back_populates="student", cascade="all, delete-orphan"
    )
    submissions = db.relationship(
        "Submission", back_populates="student", cascade="all, delete-orphan"
    )

    # --- login capability -------------------------------------------------
    # Students share the login page with Users, so Flask-Login needs a way
    # to tell the two tables apart. get_id() is prefixed; app/__init__.py's
    # user_loader strips the prefix to know which table to query.
    def get_id(self):
        return f"student-{self.id}"

    def has_login(self) -> bool:
        return self.password_hash is not None

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, raw_password)

    def is_admin(self) -> bool:
        return False

    def is_teacher(self) -> bool:
        return False

    def is_superadmin(self) -> bool:
        return False

    def is_student(self) -> bool:
        return True

    def active_cycle(self):
        """Return the first in-progress cycle for this student, across any teacher."""
        return next((c for c in self.cycles if not c.completed), None)

    def active_cycle_for(self, teacher_id):
        """Return this student's in-progress cycle that belongs to a specific teacher."""
        return next(
            (c for c in self.cycles if not c.completed and c.teacher_id == teacher_id), None
        )

    def past_cycles_for(self, teacher_id):
        """Completed cycles run by a specific teacher."""
        return [c for c in self.cycles if c.completed and c.teacher_id == teacher_id]

    def teacher_names(self) -> str:
        return ", ".join(t.name for t in self.teachers) if self.teachers else "Unassigned"

    def __repr__(self):
        return f"<Student {self.name}>"


# ---------------------------------------------------------------------------
# Cycle (a block of 8 or 10 paid lessons, run by one teacher)
# ---------------------------------------------------------------------------

class Cycle(db.Model):
    __tablename__ = "cycles"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    # A cycle is a fixed-size block of lessons used for payment tracking
    total_lessons = db.Column(db.Integer, nullable=False, default=8)

    started_on = db.Column(db.Date, default=date.today, nullable=False)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("Student", back_populates="cycles")
    teacher = db.relationship("User")
    lessons = db.relationship(
        "Lesson", back_populates="cycle", cascade="all, delete-orphan",
        order_by="Lesson.lesson_number",
    )
    feedback = db.relationship(
        "Feedback", back_populates="cycle", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("total_lessons IN (8, 10)", name="ck_cycles_total_lessons"),
    )

    # --- derived helpers ------------------------------------------------
    @property
    def lessons_completed(self) -> int:
        return sum(1 for lesson in self.lessons if lesson.completed)

    @property
    def lessons_remaining(self) -> int:
        return max(self.total_lessons - self.lessons_completed, 0)

    @property
    def progress_percent(self) -> float:
        if self.total_lessons == 0:
            return 0.0
        return round((self.lessons_completed / self.total_lessons) * 100, 1)

    def is_ready_to_complete(self) -> bool:
        return self.lessons_completed >= self.total_lessons

    def next_lesson(self):
        """Return the first not-yet-completed lesson, or None if the cycle is full."""
        return next((l for l in self.lessons if not l.completed), None)

    def mark_completed(self):
        """Mark the cycle as finished once all lessons are logged."""
        self.completed = True
        self.completed_at = datetime.utcnow()

    def __repr__(self):
        return f"<Cycle student={self.student_id} {self.lessons_completed}/{self.total_lessons}>"


# ---------------------------------------------------------------------------
# Lesson (one individual lesson within a Cycle)
# ---------------------------------------------------------------------------

class Lesson(db.Model):
    __tablename__ = "lessons"

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey("cycles.id"), nullable=False)

    # Position of this lesson within its cycle (1-based, e.g. 1..8 or 1..10)
    lesson_number = db.Column(db.Integer, nullable=False)

    scheduled_date = db.Column(db.Date, nullable=True)
    completed = db.Column(db.Boolean, default=False, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    cycle = db.relationship("Cycle", back_populates="lessons")

    __table_args__ = (
        db.UniqueConstraint("cycle_id", "lesson_number", name="uq_lesson_cycle_number"),
    )

    def mark_complete(self):
        self.completed = True
        self.completed_at = datetime.utcnow()

    def __repr__(self):
        return f"<Lesson {self.lesson_number} of cycle={self.cycle_id}>"


# ---------------------------------------------------------------------------
# GroupSession + Attendance (separate from the per-student lesson cycles)
# ---------------------------------------------------------------------------

class GroupSession(db.Model):
    """A single occurrence of a group class, used purely for attendance."""
    __tablename__ = "group_sessions"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=False)
    session_date = db.Column(db.Date, default=date.today, nullable=False)
    topic = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    group = db.relationship("Group", back_populates="sessions")
    attendance_records = db.relationship(
        "Attendance", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<GroupSession group={self.group_id} on {self.session_date}>"


class Attendance(db.Model):
    """Per-student attendance record for one GroupSession."""
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("group_sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    present = db.Column(db.Boolean, default=True, nullable=False)
    note = db.Column(db.String(255), nullable=True)

    session = db.relationship("GroupSession", back_populates="attendance_records")
    student = db.relationship("Student", back_populates="attendance_records")

    __table_args__ = (
        db.UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),
    )

    def __repr__(self):
        status = "present" if self.present else "absent"
        return f"<Attendance student={self.student_id} {status}>"


# ---------------------------------------------------------------------------
# Feedback (written once a Cycle is completed)
# ---------------------------------------------------------------------------

class Feedback(db.Model):
    __tablename__ = "feedback"

    id = db.Column(db.Integer, primary_key=True)
    cycle_id = db.Column(db.Integer, db.ForeignKey("cycles.id"), nullable=False, unique=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)

    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    cycle = db.relationship("Cycle", back_populates="feedback")
    teacher = db.relationship("User")
    student = db.relationship("Student")

    def __repr__(self):
        return f"<Feedback for cycle={self.cycle_id}>"


# ---------------------------------------------------------------------------
# Homework (material a teacher assigns to one student) + Submission
# ---------------------------------------------------------------------------

class Homework(db.Model):
    __tablename__ = "homework"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)

    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher = db.relationship("User")
    student = db.relationship("Student", back_populates="homework_assignments")
    submission = db.relationship(
        "Submission", back_populates="homework", uselist=False, cascade="all, delete-orphan"
    )

    def status(self) -> str:
        if not self.submission:
            return "not_submitted"
        if self.submission.grade is not None or self.submission.teacher_feedback:
            return "graded"
        return "submitted"

    def __repr__(self):
        return f"<Homework {self.title!r} for student={self.student_id}>"


class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    homework_id = db.Column(db.Integer, db.ForeignKey("homework.id"), nullable=False, unique=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)

    content = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(500), nullable=True)  # optional URL to external file/doc
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher_feedback = db.Column(db.Text, nullable=True)
    grade = db.Column(db.String(20), nullable=True)
    graded_at = db.Column(db.DateTime, nullable=True)

    homework = db.relationship("Homework", back_populates="submission")
    student = db.relationship("Student", back_populates="submissions")

    def __repr__(self):
        return f"<Submission for homework={self.homework_id}>"


# ---------------------------------------------------------------------------
# TimetableEntry (a recurring weekly slot for a teacher)
# ---------------------------------------------------------------------------

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class TimetableEntry(db.Model):
    """
    One recurring weekly time slot on a teacher's timetable. It's tied to
    either a Student (a 1:1 slot), a Group (a group class slot), or neither
    (a custom-labeled slot, e.g. "prep time").
    """
    __tablename__ = "timetable_entries"

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True)

    day_of_week = db.Column(db.Integer, nullable=False)  # 0 = Monday .. 6 = Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    title = db.Column(db.String(150), nullable=True)  # used when neither student nor group is set

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    teacher = db.relationship("User")
    student = db.relationship("Student")
    group = db.relationship("Group")

    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_timetable_day_of_week"),
    )

    def day_name(self) -> str:
        return DAY_NAMES[self.day_of_week]

    def label(self) -> str:
        if self.student:
            return self.student.name
        if self.group:
            return self.group.name
        return self.title or "Lesson"

    def __repr__(self):
        return f"<TimetableEntry {self.day_name()} {self.start_time}-{self.end_time} teacher={self.teacher_id}>"
