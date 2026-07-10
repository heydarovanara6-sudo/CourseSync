"""
CourseSync application factory.

Initializes Flask, SQLAlchemy (SQLite), Flask-Login, and CSRF protection,
then wires up the blueprints defined under app/routes/.
"""

import os
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from dotenv import load_dotenv

load_dotenv()  # picks up a local .env file if present; no-op otherwise

# Extensions are instantiated here (not bound to an app yet) so that
# models.py and route modules can import them without circular imports.
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"
csrf = CSRFProtect()


def create_app(config_object=None):
    """Application factory. Creates and configures the Flask app instance."""

    app = Flask(__name__, instance_relative_config=True)

    # --- Core configuration -------------------------------------------------
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-key-change-me"),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL",
            "sqlite:///" + os.path.join(app.instance_path, "coursesync.db"),
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    if config_object:
        app.config.from_object(config_object)

    if app.config["SECRET_KEY"] == "dev-secret-key-change-me" and not app.debug:
        app.logger.warning(
            "Using the default SECRET_KEY outside of debug mode. "
            "Set a real SECRET_KEY environment variable before deploying."
        )

    # Make sure the instance folder exists (this is where the SQLite file lives)
    os.makedirs(app.instance_path, exist_ok=True)

    # --- Initialize extensions -----------------------------------------------
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # --- Import models so SQLAlchemy is aware of them before create_all() ----
    from app import models  # noqa: F401

    # --- User loader for Flask-Login -----------------------------------------
    # Students share the login system with Users but live in a separate table.
    # Student.get_id() returns "student-<id>"; a plain "<id>" means a User.
    @login_manager.user_loader
    def load_user(user_id):
        if user_id.startswith("student-"):
            return models.Student.query.get(int(user_id.split("-", 1)[1]))
        return models.User.query.get(int(user_id))

    # --- Register blueprints ---------------------------------------------
    from app.routes.auth import auth_bp
    from app.routes.superadmin import superadmin_bp
    from app.routes.admin import admin_bp
    from app.routes.teacher import teacher_bp
    from app.routes.student import student_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(superadmin_bp, url_prefix="/superadmin")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(teacher_bp, url_prefix="/teacher")
    app.register_blueprint(student_bp, url_prefix="/student")

    # --- Friendly error pages -------------------------------------------
    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(500)
    def server_error(e):
        return render_template("errors/500.html"), 500

    # --- Create tables on first run (fine for SQLite / small deployments) ----
    with app.app_context():
        db.create_all()

    return app
