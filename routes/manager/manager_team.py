from flask import Blueprint, render_template, session, jsonify, request
from datetime import datetime, date, timedelta
from models.models import Employee, User
from models.attendance import Attendance
from zoneinfo import ZoneInfo
from utils.authz import ROLE_MANAGER, require_roles

IST = ZoneInfo("Asia/Kolkata")

manager_team_bp = Blueprint("manager_team_bp", __name__, url_prefix="/manager/team")


@manager_team_bp.before_request
def enforce_manager_role():
    return require_roles(ROLE_MANAGER)

# ---------------- Helper ----------------
def fmt_seconds(sec):
    sec = int(sec or 0)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02}:{m:02}:{s:02}"


def get_manager_employee():
    manager_user_id = session.get("user_id")
    if not manager_user_id:
        return None
    return Employee.query.filter_by(user_id=manager_user_id).first()

# ---------------- TEAM PAGE ----------------
@manager_team_bp.route("/")
def team_page():
    today = datetime.now(IST).date()
    return render_template("manager/team.html", today=today)

# ---------------- LIST TODAY ----------------
@manager_team_bp.route("/list_today")
def list_today():
    manager = get_manager_employee()
    if not manager:
        return jsonify([])

    today = datetime.now(IST).date()
    output = []

    # Loop through all team members
    for emp in manager.team_members:
        user = User.query.get(emp.user_id)
        name = f"{emp.first_name} {emp.last_name}" if emp else "Unknown"

        # Attendance records for today
        records = Attendance.query.filter_by(user_id=emp.user_id, date=today).all()

        if not records:
            output.append({
                "user_id": emp.user_id,
                "name": name,
                "clock_in": "-",
                "clock_out": "-",
                "worked": "00:00:00",
                "status": "No Activity",
                "date": today.isoformat()
            })
            continue

        clock_ins = [r.clock_in for r in records if r.clock_in]
        clock_outs = [r.clock_out for r in records if r.clock_out]

        first_in = min(clock_ins) if clock_ins else None
        last_out = max(clock_outs) if clock_outs else None
        total_seconds = sum(r.duration_seconds or 0 for r in records)
        status = "Active" if any(r.clock_out is None for r in records) else "Completed"

        output.append({
            "user_id": emp.user_id,
            "name": name,
            "clock_in": first_in.strftime("%I:%M:%S %p") if first_in else "-",
            "clock_out": last_out.strftime("%I:%M:%S %p") if last_out else "-",
            "worked": fmt_seconds(total_seconds),
            "status": status,
            "date": today.isoformat()
        })

    return jsonify(output)

# ---------------- ATTENDANCE DETAIL ----------------
@manager_team_bp.route("/attendance/<int:user_id>")
def attendance_detail(user_id):
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Missing date"}), 400

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    manager = get_manager_employee()
    if not manager:
        return jsonify({"error": "Manager not found"}), 403

    emp = Employee.query.filter_by(user_id=user_id).first()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    if emp.manager_emp_id != manager.id:
        return jsonify({"error": "Not authorized"}), 403

    records = Attendance.query.filter_by(user_id=user_id, date=dt).order_by(Attendance.clock_in).all()
    transactions = []
    total_seconds = 0
    last_record = None

    for r in records:
        transactions.append({
            "clock_in": r.clock_in.strftime("%I:%M:%S %p") if r.clock_in else "-",
            "clock_out": r.clock_out.strftime("%I:%M:%S %p") if r.clock_out else "-",
            "duration": fmt_seconds(r.duration_seconds)
        })
        total_seconds += r.duration_seconds or 0
        last_record = r

    last = None
    if last_record:
        last = {
            "clock_in": last_record.clock_in.strftime("%I:%M:%S %p") if last_record.clock_in else "-",
            "clock_out": last_record.clock_out.strftime("%I:%M:%S %p") if last_record.clock_out else "-",
            "worked": fmt_seconds(total_seconds),
            "status": "Active" if last_record.clock_out is None else "Completed"
        }

    return jsonify({
        "transactions": transactions,
        "last_record": last
    })

# ---------------- MONTHLY SUMMARY ----------------
@manager_team_bp.route("/monthly/<int:user_id>/<int:year>/<int:month>")
def monthly_summary(user_id, year, month):
    manager = get_manager_employee()
    if not manager:
        return jsonify({"error": "Manager not found"}), 403

    emp = Employee.query.filter_by(user_id=user_id).first()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    if emp.manager_emp_id != manager.id:
        return jsonify({"error": "Not authorized"}), 403

    first_day = date(year, month, 1)
    next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    last_day = next_month - timedelta(days=1)

    present_days = 0
    absent_days = 0
    total_seconds = 0
    late_days = 0
    early_leaves = 0

    for d in range(1, last_day.day + 1):
        curr_date = date(year, month, d)
        records = Attendance.query.filter_by(user_id=user_id, date=curr_date).all()

        if not records:
            absent_days += 1
            continue

        present_days += 1
        day_seconds = sum(r.duration_seconds or 0 for r in records)
        total_seconds += day_seconds

        clock_ins = [r.clock_in for r in records if r.clock_in]
        clock_outs = [r.clock_out for r in records if r.clock_out]
        first_in = min(clock_ins) if clock_ins else None
        last_out = max(clock_outs) if clock_outs else None

        # Late (>10 AM)
        if first_in and first_in.time() > datetime.strptime("10:00:00", "%H:%M:%S").time():
            late_days += 1
        # Early leave (<6 PM)
        if last_out and last_out.time() < datetime.strptime("18:00:00", "%H:%M:%S").time():
            early_leaves += 1

    return jsonify({
        "present_days": present_days,
        "absent_days": absent_days,
        "total_worked": fmt_seconds(total_seconds),
        "late_days": late_days,
        "early_leaves": early_leaves
    })
