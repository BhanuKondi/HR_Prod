from flask import Blueprint, jsonify, redirect, render_template, request
from models.attendance import Attendance, IST
from models.db import db
from datetime import datetime, timedelta
from utils.authz import ROLE_MANAGER, get_current_employee, require_roles
 
# ================= SHIFT CONFIG =================
SHIFT_START_HOUR = 7  # 7 AM
SHIFT_END_HOUR = 7    # Next day 7 AM
MAX_SHIFT_SECONDS = 24 * 60 * 60  # 24 hours
 
manager_attendance_bp = Blueprint(
    "manager_attendance_bp",
    __name__,
    url_prefix="/manager/attendance"
)


@manager_attendance_bp.before_request
def enforce_manager_role():
    return require_roles(ROLE_MANAGER)
 
# --------------------------------------------------
# Helper: fetch logged-in manager
# --------------------------------------------------
def current_manager():
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
    now = datetime.now(IST)
    open_logs = Attendance.query.filter_by(user_id=user_id, clock_out=None).all()
    for log in open_logs:
        if log.shift_end:
            # Make shift_end and clock_in IST-aware if naive
            shift_end = log.shift_end if log.shift_end.tzinfo else log.shift_end.replace(tzinfo=IST)
            clock_in = log.clock_in if log.clock_in.tzinfo else log.clock_in.replace(tzinfo=IST)
            if now >= shift_end:
                duration = int((shift_end - clock_in).total_seconds())
                duration = min(duration, MAX_SHIFT_SECONDS)
                log.clock_out = shift_end
                log.duration_seconds = duration
    db.session.commit()


def close_stale_open_sessions(user_id, shift_day):
    """
    Defensive cleanup:
    if any open session exists from older shift dates, close it at its shift_end.
    This prevents false "already clocked in" blocks when old open rows remain.
    """
    stale_logs = Attendance.query.filter(
        Attendance.user_id == user_id,
        Attendance.clock_out.is_(None),
        Attendance.date < shift_day,
    ).all()
    updated = False
    for log in stale_logs:
        if not log.shift_end or not log.clock_in:
            continue
        shift_end = log.shift_end if log.shift_end.tzinfo else log.shift_end.replace(tzinfo=IST)
        clock_in = log.clock_in if log.clock_in.tzinfo else log.clock_in.replace(tzinfo=IST)
        duration = int((shift_end - clock_in).total_seconds())
        log.clock_out = shift_end
        log.duration_seconds = min(max(duration, 0), MAX_SHIFT_SECONDS)
        updated = True
    if updated:
        db.session.commit()
 
# --------------------------------------------------
# Attendance UI Page
# --------------------------------------------------
@manager_attendance_bp.route("/")
def attendance_page():
    mgr = current_manager()
    if not mgr:
        return redirect("/logout")
    auto_clock_out_after_shift(mgr.user_id)
    return render_template("manager/attendance.html", manager=mgr)
 
# --------------------------------------------------
# List All Attendance Logs
# --------------------------------------------------
@manager_attendance_bp.route("/list")
def attendance_list():
    mgr = current_manager()
    if not mgr:
        return jsonify([])
 
    auto_clock_out_after_shift(mgr.user_id)
 
    logs = Attendance.query.filter_by(user_id=mgr.user_id).order_by(Attendance.id.desc()).all()
    result = [
        {
            "id": log.id,
            "transaction_no": log.transaction_no,
            "date": log.date.strftime("%d-%m-%Y"),
            "clock_in": log.clock_in.strftime("%I:%M:%S %p"),
            "clock_out": log.clock_out.strftime("%I:%M:%S %p") if log.clock_out else "-",
            "worked": (
                f"{log.duration_seconds // 3600:02}:"
                f"{(log.duration_seconds % 3600) // 60:02}:"
                f"{log.duration_seconds % 60:02}"
                if log.duration_seconds else "00:00:00"
            )
        }
        for log in logs
    ]
    return jsonify(result)
 
# --------------------------------------------------
# CLOCK-IN (SHIFT-AWARE)
# --------------------------------------------------
@manager_attendance_bp.route("/clock_in", methods=["POST"])
def clock_in():
    mgr = current_manager()
    if not mgr:
        return jsonify({"error": "Not logged in"}), 401
 
    auto_clock_out_after_shift(mgr.user_id)
 
    now = datetime.now(IST)
    shift_day = get_shift_date(now)
    close_stale_open_sessions(mgr.user_id, shift_day)
 
    # Check if already clocked-in
    active = Attendance.query.filter_by(
        user_id=mgr.user_id,
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
 
    # Count today's records
    record_count = Attendance.query.filter_by(user_id=mgr.user_id, date=shift_day).count()
 
    # Shift start/end (IST-aware)
    shift_start = datetime(
        year=now.year, month=now.month, day=now.day,
        hour=SHIFT_START_HOUR, minute=0, second=0,
        tzinfo=IST
    )
    if now.hour < SHIFT_START_HOUR:
        shift_start -= timedelta(days=1)
    shift_end = shift_start + timedelta(hours=24)
 
    new_log = Attendance(
        user_id=mgr.user_id,
        transaction_no=record_count + 1,
        date=shift_day,
        clock_in=now,
        shift_start=shift_start,
        shift_end=shift_end
    )
 
    db.session.add(new_log)
    db.session.commit()
 
    return jsonify({"success": True, "message": "Clock-in successful"})
 
# --------------------------------------------------
# CLOCK-OUT (SHIFT-AWARE)
# --------------------------------------------------
@manager_attendance_bp.route("/clock_out/<int:log_id>", methods=["POST"])
def clock_out(log_id):
    mgr = current_manager()
    if not mgr:
        return jsonify({"error": "Not logged in"}), 401
 
    auto_clock_out_after_shift(mgr.user_id)
 
    log = Attendance.query.get(log_id)
    if not log or log.user_id != mgr.user_id:
        return jsonify({"error": "Invalid attendance record"}), 400
    if log.clock_out:
        return jsonify({"error": "Already clocked out"}), 400
 
    now = datetime.now(IST)
    shift_start = log.shift_start if log.shift_start.tzinfo else log.shift_start.replace(tzinfo=IST)
    if shift_start and now < shift_start:
        return jsonify({"error": "Cannot clock out before shift start"}), 400
 
    # Update log
    clock_in = log.clock_in if log.clock_in.tzinfo else log.clock_in.replace(tzinfo=IST)
    duration = int((now - clock_in).total_seconds())
    duration = min(duration, MAX_SHIFT_SECONDS)
    log.clock_out = now
    log.duration_seconds = duration
    db.session.commit()
 
    return jsonify({"success": True, "message": "Clock-out successful"})
 
# --------------------------------------------------
# Active Session Check
# --------------------------------------------------
@manager_attendance_bp.route("/current")
def current_session():
    mgr = current_manager()
    if not mgr:
        return jsonify({"active": False})
 
    auto_clock_out_after_shift(mgr.user_id)
 
    now = datetime.now(IST)
    shift_day = get_shift_date(now)
 
    log = Attendance.query.filter_by(
        user_id=mgr.user_id,
        date=shift_day,
        clock_out=None
    ).order_by(Attendance.id.desc()).first()
 
    if log:
        return jsonify({
            "active": True,
            "clock_in": log.clock_in.isoformat(),
            "log_id": log.id
        })
 
    return jsonify({"active": False})
 
# --------------------------------------------------
# TODAY SUMMARY
# --------------------------------------------------
@manager_attendance_bp.route("/today-summary")
def today_summary():
    mgr = current_manager()
    if not mgr:
        return jsonify({"total_seconds": 0, "transactions": []})
 
    auto_clock_out_after_shift(mgr.user_id)
 
    now = datetime.now(IST)
    shift_day = get_shift_date(now)
 
    logs = Attendance.query.filter_by(
        user_id=mgr.user_id, date=shift_day
    ).order_by(Attendance.id.asc()).all()
 
    total_seconds = sum(log.duration_seconds or 0 for log in logs)
    transactions = [
    {
        "transaction_no": log.transaction_no,
        "clock_in": log.clock_in.strftime("%I:%M:%S %p") if log.clock_in else "-",
        "clock_out": log.clock_out.strftime("%I:%M:%S %p") if log.clock_out else "-",
        "duration": int(log.duration_seconds or 0)  # force integer
    }
    for log in logs
]
 
    return jsonify({"total_seconds": total_seconds, "transactions": transactions})
 
# --------------------------------------------------
# DATE RANGE SUMMARY
# --------------------------------------------------
@manager_attendance_bp.route("/range")
def manager_attendance_range():
    mgr = current_manager()
    if not mgr:
        return jsonify({"days": []})
 
    auto_clock_out_after_shift(mgr.user_id)
 
    from_date = request.args.get("from")
    to_date = request.args.get("to")
    if not from_date or not to_date:
        return jsonify({"days": []})
 
    try:
        start_date = datetime.strptime(from_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"days": []})
 
    logs = Attendance.query.filter(
        Attendance.user_id == mgr.user_id,
        Attendance.date.between(start_date, end_date)
    ).order_by(Attendance.date.asc()).all()
 
    daily_map = {}
    for log in logs:
        day = log.date.strftime("%Y-%m-%d")
 
        first_in = log.clock_in if log.clock_in.tzinfo else log.clock_in.replace(tzinfo=IST)
        last_out = log.clock_out if log.clock_out and log.clock_out.tzinfo else log.clock_out.replace(tzinfo=IST) if log.clock_out else None
        duration = log.duration_seconds or 0
 
        if day not in daily_map:
            daily_map[day] = {"date": day, "first_in": first_in, "last_out": last_out, "total_seconds": duration}
        else:
            daily_map[day]["total_seconds"] += duration
            if first_in < daily_map[day]["first_in"]:
                daily_map[day]["first_in"] = first_in
            if last_out and (not daily_map[day]["last_out"] or last_out > daily_map[day]["last_out"]):
                daily_map[day]["last_out"] = last_out
 
    days = [
        {
            "date": v["date"],
            "clock_in": v["first_in"].strftime("%I:%M:%S %p") if v["first_in"] else "-",
            "clock_out": v["last_out"].strftime("%I:%M:%S %p") if v["last_out"] else "-",
            "total_seconds": v["total_seconds"]
        }
        for v in daily_map.values()
    ]
 
    return jsonify({"days": days})
 
 
