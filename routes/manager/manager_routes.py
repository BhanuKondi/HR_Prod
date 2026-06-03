# routes/manager/manager_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from models.db import db
from models.models import Employee, User, Leavee
from models.attendance import Attendance
from datetime import date
from utils.authz import ROLE_MANAGER, get_current_employee, manager_required, require_roles
from utils.profile_photos import get_profile_photo_url, save_profile_photo

manager_bp = Blueprint("manager", __name__, url_prefix="/manager")


# ---------------- Helper Function ----------------
def current_manager():
    return get_current_employee()


# ---------------- Login Required Decorator ----------------
login_required = manager_required


@manager_bp.before_request
def enforce_manager_role():
    return require_roles(ROLE_MANAGER)


# ---------------- Dashboard Route ----------------
@manager_bp.route("/dashboard")
@login_required
def dashboard():
    mgr = current_manager()
    if not mgr:
        flash("Manager profile not found.", "danger")
        return redirect(url_for("auth.logout"))

    team = Employee.query.filter_by(manager_emp_id=mgr.id).all()
    today = date.today()
    attendance_logs = (
        Attendance.query.filter_by(user_id=mgr.user_id, date=today)
        .order_by(Attendance.transaction_no.desc())
        .all()
    )
    team_codes = [member.emp_code for member in team]
    pending_team_leaves = (
        Leavee.query.filter(
            Leavee.emp_code.in_(team_codes),
            Leavee.status.in_(["PENDING_L1", "PENDING_L2"]),
        ).count()
        if team_codes
        else 0
    )
    active_team_members = (
        Attendance.query.join(Employee, Employee.user_id == Attendance.user_id)
        .filter(Employee.manager_emp_id == mgr.id, Attendance.clock_out.is_(None))
        .count()
    )

    summary = {
        "team_size": len(team),
        "active_team_members": active_team_members,
        "pending_team_leaves": pending_team_leaves,
        "today_sessions": len(attendance_logs),
        "total_worked_seconds": sum(log.duration_seconds or 0 for log in attendance_logs),
    }

    return render_template(
        "manager/dashboard.html",
        manager=mgr,
        team=team,
        summary=summary,
        attendance_logs=attendance_logs,
    )


# ---------------- Profile Routes ----------------
@manager_bp.route("/profile")
@login_required
def profile():
    mgr = current_manager()
    if not mgr:
        flash("Manager profile not found.", "danger")
        return redirect(url_for("auth.logout"))
    display_name = mgr.user.display_name if mgr.user and mgr.user.display_name else f"{mgr.first_name} {mgr.last_name}"
    initials = "".join(part[0] for part in display_name.split()[:2]).upper() if display_name else "U"
    return render_template(
        "manager/profile.html",
        manager=mgr,
        profile_photo_url=get_profile_photo_url(mgr.user_id),
        profile_initials=initials,
    )


@manager_bp.route("/profile/edit", methods=["POST"])
@login_required
def profile_edit():
    mgr = current_manager()
    if not mgr:
        flash("Manager profile not found.", "danger")
        return redirect(url_for("auth.logout"))

    phone = request.form.get("phone")
    address = request.form.get("address")
    display_name = request.form.get("display_name")
    profile_photo = request.files.get("profile_photo")

    if phone:
        mgr.phone = phone
    if address:
        mgr.address = address
    if display_name:
        user = User.query.get(mgr.user_id)
        user.display_name = display_name
    if profile_photo and profile_photo.filename:
        saved_path = save_profile_photo(mgr.user_id, profile_photo)
        if saved_path:
            user = User.query.get(mgr.user_id)
            user.profile_photo_path = saved_path
            flash("Profile photo updated successfully.", "success")
        else:
            flash("Profile photo must be PNG, JPG, JPEG, or WEBP.", "danger")
            return redirect(url_for("manager.profile"))

    db.session.commit()
    flash("Profile updated successfully.", "success")
    return redirect(url_for("manager.profile"))
