from flask import Blueprint, jsonify, redirect, render_template, request
from models.attendance import Attendance, IST
from models.db import db
from datetime import datetime, timedelta
from utils.authz import ROLE_EMPLOYEE, get_current_employee, require_roles
 
# ================= SHIFT CONFIG =================
SHIFT_START_HOUR = 7  # 7 AM
SHIFT_END_HOUR = 7    # Next day 7 AM
MAX_SHIFT_SECONDS = 24 * 60 * 60  # 24 hours
 
employee_attendance_bp = Blueprint(
    "employee_attendance_bp",
    __name__,
    url_prefix="/employee/attendance"
)


@employee_attendance_bp.before_request
def enforce_employee_role():
    return require_roles(ROLE_EMPLOYEE)
 
# --------------------------------------------------
# Helper: convert aware → naive IST (IMPORTANT)
# --------------------------------------------------
def to_naive_ist(dt):
    if not dt:
        return None
    if dt.tzinfo:
        return dt.astimezone(IST).replace(tzinfo=None)
    return dt
 
# --------------------------------------------------
# Helper: current logged-in employee
# --------------------------------------------------
def current_employee():
    return get_current_employee()
 
# --------------------------------------------------
# Helper: shift date (7 AM → 7 AM)
# --------------------------------------------------
def get_shift_date(now):
    if now.hour < SHIFT_END_HOUR:
        return (now - timedelta(days=1)).date()
    return now.date()
 
# --------------------------------------------------
# Helper: auto clock-out after shift end
# --------------------------------------------------
def auto_clock_out_after_shift(user_id):
    now = to_naive_ist(datetime.now(IST))
 
    open_logs = Attendance.query.filter_by(
        user_id=user_id,
        clock_out=None
    ).all()
 
    for log in open_logs:
        shift_end = to_naive_ist(log.shift_end)
        clock_in = to_naive_ist(log.clock_in)
 
        if shift_end and now >= shift_end:
            duration = int((shift_end - clock_in).total_seconds())
            duration = min(duration, MAX_SHIFT_SECONDS)
 
            log.clock_out = shift_end
            log.duration_seconds = duration
 
    db.session.commit()
 
# --------------------------------------------------
# PAGE
# --------------------------------------------------
@employee_attendance_bp.route("/")
def attendance_page():
    emp = current_employee()
    if not emp:
        return redirect("/logout")
 
    auto_clock_out_after_shift(emp.user_id)
    return render_template("employee/attendance.html", employee=emp)
 
# --------------------------------------------------
# STATUS (BUTTON ENABLE / DISABLE)
# --------------------------------------------------
@employee_attendance_bp.route("/status")
def attendance_status():
    emp = current_employee()
    if not emp:
        return jsonify({"active": False})
 
    auto_clock_out_after_shift(emp.user_id)
 
    active = Attendance.query.filter_by(
        user_id=emp.user_id,
        clock_out=None
    ).first()
 
    return jsonify({"active": bool(active)})
 
# --------------------------------------------------
# CURRENT ACTIVE SESSION
# --------------------------------------------------
@employee_attendance_bp.route("/current")
def current_session():
    emp = current_employee()
    if not emp:
        return jsonify({"active": False})
 
    auto_clock_out_after_shift(emp.user_id)
 
    log = Attendance.query.filter_by(
        user_id=emp.user_id,
        clock_out=None
    ).first()
 
    if not log:
        return jsonify({"active": False})
 
    return jsonify({
        "active": True,
        "clock_in": log.clock_in.isoformat()
    })
 
# --------------------------------------------------
# TODAY SUMMARY (SHIFT-AWARE)
# --------------------------------------------------
@employee_attendance_bp.route("/today-summary")
def today_summary():
    emp = current_employee()
    if not emp:
        return jsonify({"total_seconds": 0, "transactions": []})
 
    auto_clock_out_after_shift(emp.user_id)
 
    now = to_naive_ist(datetime.now(IST))
    shift_day = get_shift_date(now)
 
    logs = Attendance.query.filter_by(
        user_id=emp.user_id,
        date=shift_day
    ).order_by(Attendance.transaction_no.asc()).all()
 
    total_seconds = 0
    transactions = []
 
    for log in logs:
        duration = log.duration_seconds or 0
        total_seconds += duration
 
        transactions.append({
            "transaction_no": log.transaction_no,
            "date": log.date.strftime("%d/%m/%Y"),
            "clock_in": log.clock_in.strftime("%I:%M %p") if log.clock_in else "-",
            "clock_out": log.clock_out.strftime("%I:%M %p") if log.clock_out else "-",
            "duration_seconds": duration
        })
 
    return jsonify({
        "total_seconds": total_seconds,
        "transactions": transactions
    })
 
# --------------------------------------------------
# CLOCK IN (SHIFT-AWARE)
# --------------------------------------------------
@employee_attendance_bp.route("/clock_in", methods=["POST"])
def clock_in():
    emp = current_employee()
    if not emp:
        return jsonify({"error": "Unauthorized"}), 401
 
    auto_clock_out_after_shift(emp.user_id)
 
    now = to_naive_ist(datetime.now(IST))
    shift_day = get_shift_date(now)
 
    active = Attendance.query.filter_by(
        user_id=emp.user_id,
        date=shift_day,
        clock_out=None
    ).first()
 
    if active:
        return jsonify({
            "success": True,
            "message": "Already clocked in",
            "log_id": active.id,
            "active": True,
            "clock_in": active.clock_in.isoformat() if active.clock_in else None,
        }), 200
 
    count = Attendance.query.filter_by(
        user_id=emp.user_id,
        date=shift_day
    ).count()
 
    shift_start = now.replace(
        hour=SHIFT_START_HOUR,
        minute=0,
        second=0,
        microsecond=0
    )
 
    if now.hour < SHIFT_START_HOUR:
        shift_start -= timedelta(days=1)
 
    shift_end = shift_start + timedelta(hours=24)
 
    log = Attendance(
        user_id=emp.user_id,
        transaction_no=count + 1,
        date=shift_day,
        clock_in=now,
        shift_start=shift_start,
        shift_end=shift_end
    )
 
    db.session.add(log)
    db.session.commit()
 
    return jsonify({"success": True})
 
# --------------------------------------------------
# CLOCK OUT (SHIFT-AWARE)
# --------------------------------------------------
@employee_attendance_bp.route("/clock_out", methods=["POST"])
def clock_out():
    emp = current_employee()
    if not emp:
        return jsonify({"error": "Unauthorized"}), 401
 
    auto_clock_out_after_shift(emp.user_id)
 
    log = Attendance.query.filter_by(
        user_id=emp.user_id,
        clock_out=None
    ).first()
 
    if not log:
        return jsonify({"error": "No active session"}), 400
 
    now = to_naive_ist(datetime.now(IST))
    clock_in = to_naive_ist(log.clock_in)
 
    duration = int((now - clock_in).total_seconds())
    duration = min(duration, MAX_SHIFT_SECONDS)
 
    log.clock_out = now
    log.duration_seconds = duration
    db.session.commit()
 
    return jsonify({"success": True})
 
# --------------------------------------------------
# DATE RANGE SUMMARY (SHIFT-AWARE, DAY WISE)
# --------------------------------------------------
@employee_attendance_bp.route("/from-to")
def attendance_from_to():
    emp = current_employee()
    if not emp:
        return jsonify({"days": []})
 
    auto_clock_out_after_shift(emp.user_id)
 
    from_str = request.args.get("from")
    to_str = request.args.get("to")
 
    try:
        from_date = datetime.strptime(from_str, "%Y-%m-%d").date()
        to_date = datetime.strptime(to_str, "%Y-%m-%d").date()
    except Exception:
        return jsonify({"days": []})
 
    logs = Attendance.query.filter(
        Attendance.user_id == emp.user_id,
        Attendance.date >= from_date,
        Attendance.date <= to_date
    ).all()
 
    days = {}
 
    for log in logs:
        key = log.date.strftime("%Y-%m-%d")
 
        if key not in days:
            days[key] = {
                "date": key,
                "first_clock_in": None,
                "last_clock_out": None,
                "total_seconds": 0
            }
 
        # ✅ First Clock In
        if log.clock_in:
            if not days[key]["first_clock_in"] or log.clock_in < days[key]["first_clock_in"]:
                days[key]["first_clock_in"] = log.clock_in
 
        # ✅ Last Clock Out
        if log.clock_out:
            if not days[key]["last_clock_out"] or log.clock_out > days[key]["last_clock_out"]:
                days[key]["last_clock_out"] = log.clock_out
 
        # ✅ Total Duration
        if log.duration_seconds:
            days[key]["total_seconds"] += log.duration_seconds
 
    return jsonify({
        "days": [
            {
                "date": d["date"],
                "clock_in": d["first_clock_in"].strftime("%I:%M %p")
                if d["first_clock_in"] else "-",
                "clock_out": d["last_clock_out"].strftime("%I:%M %p")
                if d["last_clock_out"] else "-",
                "total_seconds": d["total_seconds"]
            }
            for d in days.values()
        ]
    })
 
 
