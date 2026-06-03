from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from models.db import db
from models.models import Employee, User, Leavee
from models.attendance import Attendance, IST
from datetime import datetime, date
from utils.authz import ROLE_EMPLOYEE, employee_required, get_current_employee, require_roles
from utils.profile_photos import get_profile_photo_url, save_profile_photo

employee_bp = Blueprint("employee", __name__, url_prefix="/employee")

# ------------------------ Helper: Get logged-in employee ------------------------
def current_employee():
    return get_current_employee()

# ------------------------ Login Required Decorator ------------------------
login_required = employee_required


@employee_bp.before_request
def enforce_employee_role():
    return require_roles(ROLE_EMPLOYEE)

# ------------------------ Dashboard ------------------------
@employee_bp.route("/dashboard")
@login_required
def dashboard():
    emp = current_employee()
    today = date.today()
    attendance_logs = (
        Attendance.query.filter_by(user_id=emp.user_id, date=today)
        .order_by(Attendance.transaction_no.desc())
        .all()
    )
    pending_leaves = Leavee.query.filter(
        Leavee.emp_code == emp.emp_code,
        Leavee.status.in_(["PENDING_L1", "PENDING_L2"]),
    ).count()
    approved_leaves = Leavee.query.filter_by(emp_code=emp.emp_code, status="APPROVED").count()

    summary = {
        "today_sessions": len(attendance_logs),
        "pending_leaves": pending_leaves,
        "approved_leaves": approved_leaves,
        "total_worked_seconds": sum(log.duration_seconds or 0 for log in attendance_logs),
    }

    return render_template(
        "employee/dashboard.html",
        employee=emp,
        summary=summary,
        attendance_logs=attendance_logs,
    )

# ------------------------ Profile ------------------------
@employee_bp.route("/profile", methods=["GET"])
@login_required
def profile():
    emp = current_employee()
    display_name = emp.user.display_name if emp.user and emp.user.display_name else f"{emp.first_name} {emp.last_name}"
    initials = "".join(part[0] for part in display_name.split()[:2]).upper() if display_name else "U"
    return render_template(
        "employee/profile.html",
        employee=emp,
        profile_photo_url=get_profile_photo_url(emp.user_id),
        profile_initials=initials,
    )

@employee_bp.route("/profile/edit", methods=["POST"])
@login_required
def profile_edit():
    emp = current_employee()

    phone = request.form.get("phone")
    address = request.form.get("address")
    display_name = request.form.get("display_name")
    profile_photo = request.files.get("profile_photo")

    if phone:
        emp.phone = phone
    if address:
        emp.address = address
    if display_name:
        user = User.query.get(emp.user_id)
        user.display_name = display_name
    if profile_photo and profile_photo.filename:
        saved_path = save_profile_photo(emp.user_id, profile_photo)
        if saved_path:
            user = User.query.get(emp.user_id)
            user.profile_photo_path = saved_path
            flash("Profile photo updated successfully.", "success")
        else:
            flash("Profile photo must be PNG, JPG, JPEG, or WEBP.", "danger")
            return redirect(url_for("employee.profile"))

    db.session.commit()
    flash("Profile updated successfully.", "success")
    return redirect(url_for("employee.profile"))

# ------------------------ Leave Management ------------------------
@employee_bp.route("/leave_management")
@login_required
def leave_management():
    return redirect(url_for("employee_leaves.leave_management"))

@employee_bp.route("/leave_management/apply", methods=["POST"])
@login_required
def leave_apply():
    flash("Leave requests are now handled from the unified leave management page.", "info")
    return redirect(url_for("employee_leaves.leave_management"))

# ------------------------ Attendance ------------------------
@employee_bp.route("/attendance")
@login_required
def attendance_page():
    emp = current_employee()
    logs = Attendance.query.filter_by(user_id=emp.user_id).order_by(Attendance.id.desc()).all()
    return render_template("employee/attendance.html", employee=emp, logs=logs)

@employee_bp.route("/attendance/clock_in", methods=["POST"])
@login_required
def clock_in():
    emp = current_employee()
    now = datetime.now(IST)
    shift_start, shift_end = Attendance.get_shift_datetime(now)
    today = Attendance.get_shift_date(now)

    active = Attendance.query.filter_by(
        user_id=emp.user_id,
        clock_out=None,
    ).first()
    if active:
        return jsonify({
            "success": True,
            "message": "Already clocked in",
            "log_id": active.id,
            "active": True,
            "clock_in": active.clock_in.isoformat() if active.clock_in else None,
        }), 200

    count_today = Attendance.query.filter_by(user_id=emp.user_id, date=today).count()

    new_log = Attendance(
        user_id=emp.user_id,
        date=today,
        transaction_no=count_today + 1,
        clock_in=now,
        shift_start=shift_start,
        shift_end=shift_end,
    )

    db.session.add(new_log)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Clock-in successful",
        "log_id": new_log.id,
    })

@employee_bp.route("/attendance/clock_out/<int:log_id>", methods=["POST"])
@login_required
def clock_out(log_id):
    emp = current_employee()
    log = Attendance.query.get(log_id)

    if not log or log.user_id != emp.user_id:
        flash("Invalid request.", "danger")
        return redirect(url_for("employee.attendance_page"))

    if log.clock_out:
        flash("Already clocked out.", "warning")
        return redirect(url_for("employee.attendance_page"))

    now = datetime.now(IST)
    log.finish(now)

    db.session.commit()
    flash("Clock-out successful.", "success")
    return redirect(url_for("employee.attendance_page"))
