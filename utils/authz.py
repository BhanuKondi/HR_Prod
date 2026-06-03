from functools import wraps

from flask import flash, redirect, session, url_for

from models.models import Employee, Role, User
from sqlalchemy import func


ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_USER = "user"
ROLE_ACCOUNT_ADMIN = "account_admin"
ROLE_EMPLOYEE = ROLE_USER


def normalize_role_name(role_name: str | None) -> str | None:
    if not role_name:
        return None
    role_name = role_name.lower().replace(" ", "_")
    if role_name == ROLE_ADMIN:
        return ROLE_ADMIN
    if role_name == ROLE_ACCOUNT_ADMIN:
        return ROLE_ACCOUNT_ADMIN
    return ROLE_USER


def get_current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def get_current_role() -> str | None:
    user = get_current_user()
    if not user or not user.role or not user.role.name:
        return None
    return normalize_role_name(user.role.name)


def get_current_employee() -> Employee | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return Employee.query.filter_by(user_id=user_id).first()


def get_role_by_name(role_name: str | None) -> Role | None:
    if not role_name:
        return None
    normalized = normalize_role_name(role_name)
    exact = Role.query.filter(func.lower(Role.name) == normalized).first()
    if exact:
        return exact
    if normalized == ROLE_ACCOUNT_ADMIN:
        return Role.query.filter(func.lower(Role.name).in_(["account_admin", "account admin"])).first()
    if normalized == ROLE_USER:
        return Role.query.filter(func.lower(Role.name).in_(["employee", "manager"])).first()
    return None


def get_role_id(role_name: str | None) -> int | None:
    role = get_role_by_name(role_name)
    return role.id if role else None


def has_manager_access(user: User | None = None, employee: Employee | None = None) -> bool:
    user = user or get_current_user()
    if not user:
        return False

    if normalize_role_name(user.role.name if user.role else None) == ROLE_ADMIN:
        return False

    employee = employee or get_current_employee()
    if not employee:
        employee = Employee.query.filter_by(user_id=user.id).first()
    if not employee:
        return False

    return Employee.query.filter_by(manager_emp_id=employee.id).first() is not None


def get_base_template_for_role(role: str | None) -> str:
    role = normalize_role_name(role)
    if role == ROLE_ADMIN:
        return "admin/admin_base.html"
    if role == ROLE_ACCOUNT_ADMIN:
        if has_manager_access():
            return "manager/manager_base.html"
        if get_current_employee():
            return "employee/employee_base.html"
        return "accounts/accounts_base.html"
    if has_manager_access():
        return "manager/manager_base.html"
    return "employee/employee_base.html"


def redirect_for_role(role: str | None):
    role = normalize_role_name(role)
    if role == ROLE_ADMIN:
        return redirect("/admin/dashboard")
    if role == ROLE_ACCOUNT_ADMIN:
        if has_manager_access():
            return redirect("/manager/dashboard")
        if get_current_employee():
            return redirect("/employee/dashboard")
        return redirect("/accounts/reimbursements")
    if has_manager_access():
        return redirect("/manager/dashboard")
    if role == ROLE_USER:
        return redirect("/employee/dashboard")
    return redirect(url_for("auth.login"))


def require_roles(*allowed_roles: str):
    current_role = get_current_role()
    if "user_id" not in session or not current_role:
        flash("Please login first.", "warning")
        return redirect(url_for("auth.login"))

    if ROLE_MANAGER in allowed_roles and has_manager_access():
        return None

    if current_role == ROLE_ACCOUNT_ADMIN and ROLE_USER in allowed_roles:
        return None

    if current_role not in allowed_roles:
        flash("Access denied.", "danger")
        return redirect_for_role(current_role)

    return None


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        unauthorized = require_roles(ROLE_ADMIN, ROLE_USER, ROLE_ACCOUNT_ADMIN)
        if unauthorized:
            return unauthorized
        return f(*args, **kwargs)

    return decorated


def role_required(*allowed_roles: str):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            unauthorized = require_roles(*allowed_roles)
            if unauthorized:
                return unauthorized
            return f(*args, **kwargs)

        return decorated

    return decorator


admin_required = role_required(ROLE_ADMIN)
manager_required = role_required(ROLE_MANAGER)
employee_required = role_required(ROLE_USER)
account_admin_required = role_required(ROLE_ACCOUNT_ADMIN)
