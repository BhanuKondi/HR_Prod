import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, request, session
from models.db import db
from extensions import mail
from urllib.parse import quote_plus
from sqlalchemy import text
from utils.authz import ROLE_ACCOUNT_ADMIN, ROLE_ADMIN, ROLE_USER, get_current_role, get_role_by_name, redirect_for_role
from utils.csrf import generate_csrf_token, validate_csrf_token


def load_local_env(*paths: str) -> None:
    for path in paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)


def env_or_config(app: Flask, key: str, default=None):
    return os.getenv(key, app.config.get(key, default))


# ----------------- APP SETUP -----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_local_env(
    os.path.join(BASE_DIR, ".env.local"),
    os.path.join(BASE_DIR, ".env"),
)

app = Flask(__name__, instance_relative_config=True)
app.config.from_pyfile("config.py")

app.config["MAIL_SERVER"] = env_or_config(app, "MAIL_SERVER", "smtp.office365.com")
app.config["MAIL_PORT"] = int(env_or_config(app, "MAIL_PORT", 587))
app.config["MAIL_USE_TLS"] = str(env_or_config(app, "MAIL_USE_TLS", "true")).lower() in {"1", "true", "yes"}
app.config["MAIL_USERNAME"] = env_or_config(app, "MAIL_USERNAME", "")
app.config["MAIL_PASSWORD"] = env_or_config(app, "MAIL_PASSWORD", "")
mail_default_sender = env_or_config(app, "MAIL_DEFAULT_SENDER", "")
app.config["MAIL_DEFAULT_SENDER"] = mail_default_sender or app.config["MAIL_USERNAME"] or None
app.config["APP_BASE_URL"] = env_or_config(app, "APP_BASE_URL", None)

mail.init_app(app)

password = quote_plus(str(env_or_config(app, "MYSQL_PASSWORD", "")))
mysql_host = env_or_config(app, "MYSQL_HOST", "localhost")
mysql_port = int(env_or_config(app, "MYSQL_PORT", 3306))
mysql_user = env_or_config(app, "MYSQL_USER", "root")
mysql_database = env_or_config(app, "MYSQL_DATABASE", "")
app.config["SQLALCHEMY_DATABASE_URI"] = (
    f"mysql+pymysql://{mysql_user}:{password}"
    f"@{mysql_host}:{mysql_port}/{mysql_database}"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.secret_key = env_or_config(app, "SECRET_KEY", "change-me")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = env_or_config(app, "SESSION_COOKIE_SAMESITE", "Lax")
app.config["SESSION_COOKIE_SECURE"] = str(env_or_config(app, "SESSION_COOKIE_SECURE", "false")).lower() in {"1", "true", "yes"}
app.config["REMEMBER_COOKIE_HTTPONLY"] = True
app.config["REMEMBER_COOKIE_SECURE"] = app.config["SESSION_COOKIE_SECURE"]
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
    minutes=int(env_or_config(app, "PERMANENT_SESSION_LIFETIME_MINUTES", 30))
)

# ----------------- DATABASE INIT -----------------
db.init_app(app)


@app.context_processor
def inject_csrf_token():
    return {"csrf_token": generate_csrf_token()}


CSRF_EXEMPT_ENDPOINTS = {
    "api_emp.api_create_employee",
    "api_emp.api_delete_employee",
    "api_emp.api_enable_employee",
    "api_emp.api_disable_employee",
}


@app.before_request
def enforce_csrf_for_post_requests():
    if request.method != "POST":
        return None

    endpoint = request.endpoint or ""
    if endpoint in CSRF_EXEMPT_ENDPOINTS or endpoint.startswith("api_emp."):
        return None

    submitted_token = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
    )
    if validate_csrf_token(submitted_token):
        return None

    if request.is_json:
        return jsonify({"error": "CSRF validation failed"}), 400
    return "CSRF validation failed. Please refresh the page and try again.", 400





# ----------------- MODELS -----------------
from models.models import User, Role
from utils.company_service import seed_companies

# ----------------- DEFAULT ADMIN CREATION -----------------
def ensure_core_roles():
    with app.app_context():
        db.create_all()
        existing_roles = {role.name.lower().replace(" ", "_"): role for role in Role.query.all()}
        changed = False

        if ROLE_ADMIN not in existing_roles:
            db.session.add(Role(name="Admin"))
            changed = True

        if ROLE_USER not in existing_roles:
            db.session.add(Role(name="User"))
            changed = True

        if ROLE_ACCOUNT_ADMIN not in existing_roles:
            db.session.add(Role(name="Account Admin"))
            changed = True

        if changed:
            db.session.commit()


def ensure_user_profile_photo_column():
    with app.app_context():
        with db.engine.begin() as connection:
            columns = connection.execute(text("SHOW COLUMNS FROM users LIKE 'profile_photo_path'")).fetchall()
            if not columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN profile_photo_path VARCHAR(255) NULL"))


def ensure_company_columns():
    with app.app_context():
        db.create_all()
        with db.engine.begin() as connection:
            reimbursement_columns = connection.execute(
                text("SHOW COLUMNS FROM reimbursement_requests LIKE 'company_id'")
            ).fetchall()
            if not reimbursement_columns:
                connection.execute(text("ALTER TABLE reimbursement_requests ADD COLUMN company_id INT NULL"))

            accounts_columns = connection.execute(
                text("SHOW COLUMNS FROM accounts_requests LIKE 'company_id'")
            ).fetchall()
            if not accounts_columns:
                connection.execute(text("ALTER TABLE accounts_requests ADD COLUMN company_id INT NULL"))


def create_default_admin():
    with app.app_context():
        db.create_all()  # Ensure tables exist

        # Ensure Admin role exists
        admin_role = get_role_by_name("admin")
        if not admin_role:
            admin_role = Role(name="Admin")
            db.session.add(admin_role)
            db.session.commit()

        enable_default_admin = str(env_or_config(app, "ENABLE_DEFAULT_ADMIN", "false")).lower() in {"1", "true", "yes"}
        if not enable_default_admin:
            return

        # Ensure default admin user exists
        admin_email = env_or_config(app, "DEFAULT_ADMIN_EMAIL", "admin@example.com")
        admin_password = env_or_config(app, "DEFAULT_ADMIN_PASSWORD")
        if not admin_password:
            print("Skipping default admin creation because DEFAULT_ADMIN_PASSWORD is not set.")
            return

        admin = User.query.filter_by(email=admin_email).first()
        if not admin:
            admin = User(
                email=admin_email,
                display_name="Administrator",
                role_id=admin_role.id,
                is_active=True,
                must_change_password=True
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"âœ” Default admin created for {admin_email}")

ensure_core_roles()
ensure_user_profile_photo_column()
ensure_company_columns()
with app.app_context():
    seed_companies()
create_default_admin()

# ----------------- BLUEPRINT IMPORTS -----------------
# Auth routes
from auth.auth import auth_bp

# Admin routes
from routes.admin.admin_routes import admin_bp
from routes.admin.admin_attendance import admin_attendance_bp
from routes.admin.attendance_routes import attendance_bp

# Employee routes
from routes.employee.employee_routes import employee_bp
from routes.employee.attendance_employee import employee_attendance_bp


# Manager routes
from routes.manager.manager_routes import manager_bp
from routes.manager.attendance_manager import manager_attendance_bp
from routes.reimbursements.employee_reimbursements import employee_reimbursements_bp
from routes.reimbursements.manager_reimbursements import manager_reimbursements_bp
from routes.reimbursements.account_reimbursements import account_reimbursements_bp
from routes.reimbursements.admin_reimbursements import admin_reimbursements_bp
from routes.loans.employee_loans import employee_loans_bp
from routes.loans.manager_loans import manager_loans_bp
from routes.loans.account_loans import account_loans_bp
from routes.admin.admin_loans import admin_loans_bp
from routes.accounts.account_requests import account_requests_bp
from routes.accounts.manager_account_requests import manager_account_requests_bp
from routes.admin.admin_account_requests import admin_account_requests_bp

from routes.manager.manager_team import manager_team_bp  # <-- Add this
from routes.employee.employee_leaves import employee_lbp
from routes.admin.admin_leaves import admin_lbp
from routes.manager.manager_leaves import manager_lbp
# Settings routes
from routes.settings.settings import settings_bp
from routes.api_employees import api_emp
from routes.admin.admin_payroll_routes import admin_payroll_bp
from routes.admin.admin_salary_revisions import admin_salary_revisions_bp
from routes.employee.employee_payroll import employee_payroll_bp
from routes.manager.manager_payroll import manager_payroll_bp
app.register_blueprint(admin_payroll_bp)
app.register_blueprint(admin_salary_revisions_bp)
# ----------------- BLUEPRINT REGISTRATION -----------------
# Auth
app.register_blueprint(auth_bp)

# Admin
app.register_blueprint(admin_bp)
app.register_blueprint(admin_attendance_bp)
app.register_blueprint(attendance_bp)

# Employee
app.register_blueprint(employee_attendance_bp)
app.register_blueprint(employee_bp)


# Manager
app.register_blueprint(manager_attendance_bp)  # /manager/attendance
      # /manager/leave_management
app.register_blueprint(manager_team_bp)        # /manager/team
app.register_blueprint(manager_bp)             # /manager/dashboard, profile, etc.
app.register_blueprint(manager_payroll_bp)
app.register_blueprint(manager_reimbursements_bp)
# Settings
app.register_blueprint(settings_bp)

app.register_blueprint(employee_lbp)
app.register_blueprint(admin_lbp)
app.register_blueprint(manager_lbp)
app.register_blueprint(api_emp)


app.register_blueprint(employee_payroll_bp)
app.register_blueprint(employee_reimbursements_bp)
app.register_blueprint(employee_loans_bp)
app.register_blueprint(account_reimbursements_bp)
app.register_blueprint(account_loans_bp)
app.register_blueprint(admin_reimbursements_bp)
app.register_blueprint(admin_loans_bp)
app.register_blueprint(account_requests_bp)
app.register_blueprint(manager_account_requests_bp)
app.register_blueprint(manager_loans_bp)
app.register_blueprint(admin_account_requests_bp)


# ----------------- DEFAULT ROUTE -----------------
@app.route("/")
def index():
    if "user_id" not in session:
        return redirect("/login")
    return redirect_for_role(get_current_role())

# ----------------- TEST ROUTE -----------------
@app.route("/test")
def test():
    return "Flask app is running!"


@app.route("/health/db")
def health_db():
    try:
        with db.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return jsonify({
            "status": "ok",
            "database": "reachable"
        }), 200
    except Exception as exc:
        return jsonify({
            "status": "error",
            "database": "unreachable",
            "message": str(exc)
        }), 500

# ----------------- RUN -----------------
if __name__ == "__main__":
    #debug_mode = str(env_or_config(app, "FLASK_DEBUG", "false")).lower() in {"1", "true", "yes"}
    app.run(host="0.0.0.0", port=5051)

