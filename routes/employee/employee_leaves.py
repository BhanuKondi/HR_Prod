import calendar
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func

from models.models import Employee, Holiday, LeaveApprovalConfig, Leavee, User, db
from utils.authz import ROLE_EMPLOYEE, employee_required, get_current_employee, require_roles
from utils.email_service import send_email

employee_lbp = Blueprint(
    "employee_leaves",
    __name__,
    url_prefix="/employee/leaves"
)


@employee_lbp.before_request
def enforce_employee_role():
    return require_roles(ROLE_EMPLOYEE)


login_required = employee_required


def current_employee():
    return get_current_employee()


def get_user_email(user_id):
    user = User.query.filter_by(id=user_id).first()
    return user.email if user else None


def get_total_cl_for_year():
    cl_start_month = 3
    today = datetime.now()
    current_month = today.month
    current_day = today.day

    if current_month < cl_start_month:
        return 0

    last_day = calendar.monthrange(today.year, current_month)[1]
    months_completed = current_month - cl_start_month if current_day < last_day else current_month - cl_start_month + 1
    return months_completed * 0.5


def get_consumed_leaves(emp_code, leave_type):
    current_year = datetime.now().year
    total = db.session.query(
        func.coalesce(func.sum(Leavee.total_days), 0.0)
    ).filter(
        Leavee.emp_code == emp_code,
        Leavee.leave_type == leave_type,
        Leavee.status == "APPROVED",
        func.extract("year", Leavee.start_date) == current_year,
    ).scalar()
    return float(total)


def get_available_cl(emp_code):
    return round(get_total_cl_for_year() - get_consumed_leaves(emp_code, "Casual Leave"), 2)


def get_available_sl(emp_code):
    return round(6 - get_consumed_leaves(emp_code, "Sick Leave"), 2)


@employee_lbp.route("/leave-management")
@login_required
def leave_management():
    emp = current_employee()
    holidays = Holiday.query.all()
    config = LeaveApprovalConfig.query.first()

    show_approvals_tab = False
    if config:
        if not config.use_manager_l1 and config.level1_approver_id and int(config.level1_approver_id) == emp.user_id:
            show_approvals_tab = True
        if config.level2_approver_id and int(config.level2_approver_id) == emp.user_id:
            show_approvals_tab = True
        if config.use_manager_l1 and Employee.query.filter_by(manager_emp_id=emp.id).first():
            show_approvals_tab = True

    return render_template(
        "employee/leave_management.html",
        employee=emp,
        holidays=holidays,
        show_approvals_tab=show_approvals_tab,
    )


@employee_lbp.route("/leave/submit", methods=["POST"])
@login_required
def submit_leave():
    emp = current_employee()
    start = datetime.strptime(request.form["start_date"], "%Y-%m-%d").date()
    end = datetime.strptime(request.form["end_date"], "%Y-%m-%d").date()
    is_half_day = request.form.get("is_half_day") == "true"
    leave_type = request.form["leave_type"]

    if is_half_day:
        end = start
        total_days = 0.5
    else:
        total_days = float((end - start).days + 1)

    if is_half_day and start != end:
        flash("For half day, start and end must match", "danger")
        return redirect(url_for("employee_leaves.leave_management"))

    if leave_type == "Casual Leave":
        available = get_available_cl(emp.emp_code)
        if available <= 0:
            flash("No Casual Leave available", "danger")
            return redirect(url_for("employee_leaves.leave_management"))
        if available < 1 and not is_half_day:
            flash("Only half-day Casual Leave available. Please select Half Day.", "danger")
            return redirect(url_for("employee_leaves.leave_management"))
        if total_days > available:
            flash(f"Only {available} CL available", "danger")
            return redirect(url_for("employee_leaves.leave_management"))
    elif leave_type == "Sick Leave":
        available = get_available_sl(emp.emp_code)
        if available <= 0:
            flash("No Sick Leave available", "danger")
            return redirect(url_for("employee_leaves.leave_management"))
        if available < 1 and not is_half_day:
            flash("Only half-day Sick Leave available. Please select Half Day.", "danger")
            return redirect(url_for("employee_leaves.leave_management"))
        if total_days > available:
            flash(f"Only {available} SL available", "danger")
            return redirect(url_for("employee_leaves.leave_management"))

    config = LeaveApprovalConfig.query.first()
    if config.use_manager_l1:
        if not emp.manager:
            flash("Manager not configured!", "danger")
            return redirect(url_for("employee_leaves.leave_management"))
        level1_id = emp.manager.user_id
    else:
        level1_id = int(config.level1_approver_id)
    level2_id = int(config.level2_approver_id)

    leave = Leavee(
        emp_code=emp.emp_code,
        start_date=start,
        end_date=end,
        total_days=total_days,
        reason=request.form["reason"],
        employee_name=f"{emp.first_name} {emp.last_name}",
        leave_type=leave_type,
        status="PENDING_L1",
        level1_approver_id=level1_id,
        level2_approver_id=level2_id,
        current_approver_id=level1_id,
    )
    db.session.add(leave)
    db.session.commit()

    try:
        l1_email = get_user_email(level1_id)
        if l1_email:
            send_email(
                "New Leave Request - Action Required",
                [l1_email],
                f"""
Hello,

A new leave request has been submitted and requires your approval.

Employee Name : {emp.first_name} {emp.last_name}
Leave Type    : {leave_type}
From Date     : {start}
To Date       : {end}
Total Days    : {total_days}
Reason        : {request.form['reason']}

Please open the below link to review the request.
http://74.249.73.140:5050/manager/leaves/leave-management

Regards,
HR System
""",
            )
    except Exception as exc:
        print("Email error:", exc)

    flash("Leave submitted!", "success")
    return redirect(url_for("employee_leaves.leave_management"))


@employee_lbp.route("/leave/my-approvals")
@login_required
def my_approvals():
    emp = current_employee()
    config = LeaveApprovalConfig.query.first()
    level1 = config.level1_approver_id
    level2 = config.level2_approver_id

    all_pending = Leavee.query.filter_by(current_approver_id=emp.user_id).all()
    final_list = []

    for leave in all_pending:
        if emp.user_id == level1 and leave.emp_code == emp.emp_code:
            leave.current_approver_id = level2
            leave.status = "PENDING_L2"
            db.session.commit()
            continue
        if emp.user_id == level2 and leave.emp_code == emp.emp_code:
            leave.status = "APPROVED"
            leave.current_approver_id = None
            db.session.commit()
            continue

        final_list.append({
            "id": leave.id,
            "emp_code": leave.emp_code,
            "employee_name": leave.employee_name,
            "start": leave.start_date.strftime("%Y-%m-%d"),
            "end": leave.end_date.strftime("%Y-%m-%d"),
            "days": leave.total_days,
            "reason": leave.reason,
            "status": leave.status,
            "leave_type": leave.leave_type,
            "level1_decision_date": leave.level1_decision_date,
            "level2_decision_date": leave.level2_decision_date,
        })

    return jsonify(final_list)


@employee_lbp.route("/leave/my-requests")
@login_required
def my_requests():
    emp = current_employee()
    leaves = Leavee.query.filter_by(emp_code=emp.emp_code).all()
    return jsonify([
        {
            "id": leave.id,
            "start": leave.start_date.strftime("%Y-%m-%d"),
            "end": leave.end_date.strftime("%Y-%m-%d"),
            "days": float(leave.total_days),
            "reason": leave.reason,
            "status": leave.status,
            "leave_type": leave.leave_type,
        }
        for leave in leaves
    ])


@employee_lbp.route("/leave/approve/<int:leave_id>", methods=["POST"])
@login_required
def approve_leave(leave_id):
    emp = current_employee()
    leave = Leavee.query.get_or_404(leave_id)

    if leave.current_approver_id != emp.user_id:
        return jsonify({"error": "Not authorized"}), 403

    if leave.status == "PENDING_L1":
        leave.status = "PENDING_L2"
        leave.level1_decision_date = datetime.now()
        leave.current_approver_id = leave.level2_approver_id
        try:
            l2_email = get_user_email(leave.level2_approver_id)
            if l2_email:
                send_email(
                    "Leave Request Pending - Level 2 Approval",
                    [l2_email],
                    f"""
Hello,

A leave request has been approved by Level 1 and is now pending your approval.

Employee Name : {leave.employee_name}
Leave Type    : {leave.leave_type}
From Date     : {leave.start_date}
To Date       : {leave.end_date}
Total Days    : {leave.total_days}
Reason        : {leave.reason}

Kindly open below link to review and take appropriate action.
http://74.249.73.140:5050/manager/leaves/leave-management
Regards,
HR System
""",
                )
        except Exception as exc:
            print("Email error (L2):", exc)
    elif leave.status == "PENDING_L2":
        leave.status = "APPROVED"
        leave.level2_decision_date = datetime.now()
        leave.current_approver_id = None
        try:
            emp_record = Employee.query.filter_by(emp_code=leave.emp_code).first()
            emp_email = get_user_email(emp_record.user_id)
            if emp_email:
                send_email(
                    "Leave Approved",
                    [emp_email],
                    f"""
Hello,

Your leave request has been approved successfully.

Leave Details:
---------------
Leave Type : {leave.leave_type}
From       : {leave.start_date}
To         : {leave.end_date}
Days       : {leave.total_days}

Enjoy your time off.

Regards,
HR Team
""",
                )
        except Exception as exc:
            print("Email error (Approval):", exc)

    db.session.commit()
    return jsonify({"success": True})


@employee_lbp.route("/leave/reject/<int:leave_id>", methods=["POST"])
@login_required
def reject_leave(leave_id):
    emp = current_employee()
    leave = Leavee.query.get_or_404(leave_id)

    if leave.current_approver_id != emp.user_id:
        return jsonify({"error": "Not authorized"}), 403

    if leave.status == "PENDING_L1":
        leave.status = "REJECTED_L1"
        leave.level1_decision_date = datetime.now()
    elif leave.status == "PENDING_L2":
        leave.status = "REJECTED_L2"
        leave.level2_decision_date = datetime.now()

    leave.current_approver_id = None
    db.session.commit()

    try:
        emp_record = Employee.query.filter_by(emp_code=leave.emp_code).first()
        emp_email = get_user_email(emp_record.user_id)
        if emp_email:
            send_email(
                "Leave Request Rejected",
                [emp_email],
                f"""
Hello,

We regret to inform you that your leave request has been rejected.

Leave Details:
---------------
Leave Type : {leave.leave_type}
From       : {leave.start_date}
To         : {leave.end_date}
Days       : {leave.total_days}
Status     : {leave.status}

For more details, please contact your manager.

Regards,
HR Team
""",
            )
    except Exception as exc:
        print("Email error (Reject):", exc)

    return jsonify({"success": True})


@employee_lbp.route("/leave/balance")
@login_required
def leave_balance():
    emp = current_employee()
    return jsonify({
        "cl": get_available_cl(emp.emp_code),
        "sl": get_available_sl(emp.emp_code),
    })
