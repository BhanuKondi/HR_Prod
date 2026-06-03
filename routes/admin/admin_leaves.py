from flask import Blueprint, render_template, session, redirect, url_for, jsonify, request
from models.models import Employee, Leavee, Holiday, db
from datetime import datetime
from utils.authz import ROLE_ADMIN, get_current_employee, require_roles

admin_lbp = Blueprint(
    "admin_leaves",
    __name__,
    url_prefix="/admin/leaves"
)

# ---------------- Helper ----------------
def current_admin():
    return get_current_employee()

# ---------------- BEFORE REQUEST ----------------
@admin_lbp.before_request
def check_admin():
    return require_roles(ROLE_ADMIN)

# ---------------- LEAVE MANAGEMENT PAGE ----------------
@admin_lbp.route("/leave-management")
def leave_management():
    holidays = Holiday.query.all()
    return render_template(
        "admin/leave_management.html",
        holidays=holidays
    )

# ---------------- PENDING APPROVALS ----------------
@admin_lbp.route("/leave/pending-approvals")
def pending_approvals():
    user_id = session.get("user_id")
    
    # Fetch leaves where current approver matches Employee.id
    pending = Leavee.query.filter_by(current_approver_id=user_id).all()

    return jsonify([
        {
            "id": l.id,
            "emp_code": l.emp_code,
            "employee_name":l.employee_name,
            "start": l.start_date.strftime("%Y-%m-%d"),
            "end": l.end_date.strftime("%Y-%m-%d"),
            "days": l.total_days,
            "leave_type":l.leave_type,
            "reason": l.reason,
            "status": l.status,
            "level1_decision_date": l.level1_decision_date,
            "level2_decision_date": l.level2_decision_date
        }
        for l in pending
    ])

# ---------------- APPROVE / REJECT ----------------
@admin_lbp.route("/leave/approve/<int:leave_id>", methods=["POST"])
def approve_leave(leave_id):
    user_id = session.get("user_id")
    leave = Leavee.query.get_or_404(leave_id)

    if leave.current_approver_id != user_id:
        return jsonify({"error": "Not authorized"}), 403

    if leave.status == "PENDING_L1":
        leave.status = "PENDING_L2"
        leave.level1_decision_date = datetime.now()
        leave.current_approver_id = leave.level2_approver_id

    elif leave.status == "PENDING_L2":
        leave.status = "APPROVED"
        leave.level2_decision_date = datetime.now()
        leave.current_approver_id = None

    db.session.commit()
    return jsonify({"success": True})

@admin_lbp.route("/leave/reject/<int:leave_id>", methods=["POST"])
def reject_leave(leave_id):
    user_id = session.get("user_id")
    leave = Leavee.query.get_or_404(leave_id)

    if leave.current_approver_id != user_id:
        return jsonify({"error": "Not authorized"}), 403

    if leave.status == "PENDING_L1":
        leave.status = "REJECTED_L1"
        leave.level1_decision_date = datetime.now()
    elif leave.status == "PENDING_L2":
        leave.status = "REJECTED_L2"
        leave.level2_decision_date = datetime.now()

    leave.current_approver_id = None
    db.session.commit()
    return jsonify({"success": True})

# ---------------- EMPLOYEE LEAVE SUMMARY ----------------
@admin_lbp.route("/leave/summary")
def leave_summary():
    employees = Employee.query.all()
    summary = []

    today = datetime.now()
    current_year = today.year
    current_month = today.month

    # Financial year starts in March
    if current_month >= 3:
        months_passed = current_month - 2   # March = 1
    else:
        months_passed = current_month + 10  # Jan=11, Feb=12

    TOTAL_CL = round(months_passed * 0.5, 2)
    TOTAL_SL = 6

    for e in employees:
        emp = e.emp_code

        # =========================
        # CASUAL LEAVE CONSUMED (ONLY THIS YEAR)
        # =========================
        cl_consumed = db.session.query(
            db.func.coalesce(db.func.sum(Leavee.total_days), 0)
        ).filter(
            Leavee.emp_code == emp,
            Leavee.status == "APPROVED",
            Leavee.leave_type == "Casual Leave",
            db.func.extract('year', Leavee.start_date) == current_year
        ).scalar()

        cl_consumed = float(cl_consumed or 0)

        # =========================
        # SICK LEAVE CONSUMED
        # =========================
        sl_consumed = db.session.query(
            db.func.coalesce(db.func.sum(Leavee.total_days), 0)
        ).filter(
            Leavee.emp_code == emp,
            Leavee.status == "APPROVED",
            Leavee.leave_type == "Sick Leave",
            db.func.extract('year', Leavee.start_date) == current_year
        ).scalar()

        sl_consumed = float(sl_consumed or 0)

        # =========================
        # LWP
        # =========================
        lwp = db.session.query(
            db.func.coalesce(db.func.sum(Leavee.total_days), 0)
        ).filter(
            Leavee.emp_code == emp,
            Leavee.status == "APPROVED",
            Leavee.leave_type == "Leave Without Pay",
            db.func.extract('year', Leavee.start_date) == current_year
        ).scalar()

        lwp = float(lwp or 0)

        # =========================
        # REMAINING CALCULATION
        # =========================
        cl_remaining = round(TOTAL_CL - cl_consumed, 2)
        sl_remaining = TOTAL_SL - sl_consumed

        summary.append({
            "emp_code": emp,
            "name": f"{e.first_name} {e.last_name}",

            # 🔥 CL (DYNAMIC)
            "total_casual": round(TOTAL_CL, 2),
            "casual_consumed": cl_consumed,
            "casual_remaining": max(cl_remaining, 0),

            # SL (FIXED)
            "total_sick": TOTAL_SL,
            "sick_consumed": sl_consumed,
            "sick_remaining": max(sl_remaining, 0),

            "LWP": lwp
        })

    return jsonify(summary)
@admin_lbp.route("/add-holiday", methods=["GET", "POST"])
def add_holiday():
    if request.method == "POST":
        occasion = request.form.get("occasion")   # NOT name
        date = request.form.get("date")           # this is correct

        if not occasion or not date:
            
            return redirect(url_for("admin_leaves.add_holiday"))

        new_holiday = Holiday(occasion=occasion, date=date)
        db.session.add(new_holiday)
        db.session.commit()

        
        return redirect(url_for("admin_leaves.leave_management"))

    return render_template("admin/add_holiday.html")
# ---------------- DELETE HOLIDAY ----------------
@admin_lbp.route("/delete-holiday/<int:holiday_id>", methods=["POST"])
def delete_holiday(holiday_id):
    holiday = Holiday.query.get_or_404(holiday_id)

    db.session.delete(holiday)
    db.session.commit()

    return jsonify({"success": True})
