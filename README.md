# CourseSync

A course/lesson management app for admins and teachers — 100% free stack:
Python (Flask), SQLite, and Tailwind CSS (via CDN).

## Status: Step 2 — full working frontend

Backend (Step 1) plus a complete, styled UI: login, admin overview, teacher
dashboard, per-student lesson tracker, and group/attendance management.

### Design
- **Signature element — the Stamp Card**: a row of circles, one per lesson
  in an 8/10 cycle, filling in like brass stamps as lessons are logged.
- **Palette**: deep chalkboard ink, sage-ivory paper, brass accent, muted
  brick for alerts.
- **Type**: Fraunces (display), IBM Plex Sans (body), IBM Plex Mono (numbers).

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env            # then edit SECRET_KEY before deploying anywhere real
python seed.py                  # create the first Admin account
python run.py                   # visit http://127.0.0.1:5000
```

By default `FLASK_DEBUG=0` (production-safe). For local development with
auto-reload, set `FLASK_DEBUG=1` in `.env` or `export FLASK_DEBUG=1`.

## Deploying

The app is a standard Flask app + `gunicorn`, so it runs on any host that
supports Python (Render, Railway, Fly.io, a plain VPS, etc.):

```bash
gunicorn "run:app"
```

A `Procfile` is included for platforms that read one. Before deploying:

1. Set a real `SECRET_KEY` (see `.env.example` for how to generate one).
2. Point `DATABASE_URL` at a persistent database if your host's filesystem
   is ephemeral (SQLite's single file works fine on hosts with persistent disk).
3. Run `python seed.py` once against the production database to create the
   first admin account.

## Security notes

- Passwords are hashed with Werkzeug's `generate_password_hash` — never stored in plain text.
- All forms are protected against CSRF via Flask-WTF.
- Session cookies are `HttpOnly` and `SameSite=Lax`.
- Every teacher/admin route checks the logged-in user's role before touching data.

## Data model

- **User** — Admins and Teachers (`role` column distinguishes them).
- **Student** — belongs to exactly one Teacher; optionally belongs to one Group.
- **Group** — a set of students taught together by one Teacher.
- **Cycle** — a payment cycle of **8 or 10 lessons** for one student.
- **Lesson** — one lesson within a Cycle; toggling it "complete" advances the cycle.
- **GroupSession / Attendance** — separate attendance tracking for group classes,
  independent of each student's individual lesson cycle.
- **Feedback** — one-to-one with a Cycle; written once all lessons in the
  cycle are complete.

## What's in the UI

- **Login** (`/login`) — split-screen, stamp card in the hero.
- **Admin overview** (`/admin/dashboard`) — add teachers, add students, assign/reassign.
- **Teacher dashboard** (`/teacher/dashboard`) — every assigned student with live cycle progress.
- **Lesson tracker** (`/teacher/students/<id>`) — full stamp card, log lessons one at a time,
  leave feedback and close a cycle once all lessons are stamped, see past cycles.
- **Groups** (`/teacher/groups`, `/teacher/groups/<id>`) — create groups, add students to a
  group, log a session and mark attendance (kept separate from individual lesson cycles).

## Multi-tenancy & roles

- **Superadmin** — no course of their own; creates Courses and their owners from the Courses page. Bootstrap this account with `python seed.py`.
- **Admin (Course Owner)** — runs one course entirely independently. Never sees another course's teachers, students, cycles, homework, or timetable — every query is scoped by `course_id`, and cross-course IDs 404 rather than leak data.
- **Teacher** — belongs to one course; sees only their own assigned students, groups, homework, and timetable.
- **Student** — belongs to one course; read-only except for submitting homework, sees only their own progress and timetable.

## Timetable

Each teacher manages their own recurring weekly timetable (a slot for a student, a group, or a custom label). Admins see every teacher's timetable in their course (read-only). Students see only the slots that involve them (directly, or via a group they belong to).

## What's included, end to end

- Full data model (Course, Users, Students, Groups, Cycles, Lessons, GroupSessions, Attendance, Feedback, Homework, Submission, TimetableEntry)
- Working auth for all four roles (hashed passwords, Flask-Login sessions)
- Complete UI: superadmin course management, admin overview + drill-down + timetable, teacher dashboard + lesson tracker + groups + homework + timetable, student dashboard + homework + timetable
- CSRF protection on every form
- Styled 404 / 403 / 500 error pages
- `.env`-based configuration, `.gitignore`, `Procfile` + `gunicorn` for deployment

## Possible next steps

- Password-reset / "forgot password" flow
- CSV export of cycle/attendance history for admins
- Automated tests (pytest) covering the routes exercised manually during development
