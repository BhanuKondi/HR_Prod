from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from models.models import (
    Employee,
    EmailDeliveryConfig,
    User,
    Role,
    LeaveApprovalConfig,
    EmployeeSalary,
    EmployeeAccount,
    Leavee,
    ReimbursementRequest,
    AccountsRequest,
    EmployeeLoan,
)
from models.db import db
from sqlalchemy import cast, Integer, func
from datetime import datetime   # ✅ REQUIRED
from models.attendance import Attendance
from utils.authz import ROLE_ACCOUNT_ADMIN, ROLE_ADMIN, ROLE_USER, get_role_id, has_manager_access, normalize_role_name, require_roles
from utils.email_config_service import DELIVERY_INTENDED, DELIVERY_TEST, get_email_delivery_config
from utils.reimbursement_service import STATUS_PENDING_MANAGER, STATUS_PENDING_FINANCE
from utils.accounts_request_service import STATUS_PENDING_APPROVAL as AR_STATUS_PENDING_APPROVAL
from utils.loan_service import STATUS_PENDING_APPROVAL as LOAN_STATUS_PENDING_APPROVAL
 
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")
 
# =====================================================
# ADMIN ACCESS CHECK
# =====================================================
@admin_bp.before_request
def check_admin():
    return require_roles(ROLE_ADMIN)
 
 
# =====================================================
# DASHBOARD
# =====================================================
@admin_bp.route("/dashboard")
def dashboard():
    total_employees = Employee.query.count()
    active_employees = Employee.query.filter_by(status="Active").count()
    manager_count = (
        db.session.query(Employee.manager_emp_id)
        .filter(Employee.manager_emp_id.isnot(None))
        .distinct()
        .count()
    )
    pending_leaves = Leavee.query.filter(Leavee.status.in_(["PENDING_L1", "PENDING_L2"])).count()
    open_attendance_sessions = Attendance.query.filter_by(clock_out=None).count()
    pending_reimbursement_queue = ReimbursementRequest.query.filter(
        ReimbursementRequest.status.in_([STATUS_PENDING_MANAGER, STATUS_PENDING_FINANCE])
    ).count()
    pending_accounts_request_queue = AccountsRequest.query.filter_by(
        status=AR_STATUS_PENDING_APPROVAL
    ).count()
    pending_loan_queue = EmployeeLoan.query.filter_by(
        status=LOAN_STATUS_PENDING_APPROVAL
    ).count()

    summary = {
        "total_employees": total_employees,
        "active_employees": active_employees,
        "manager_count": manager_count,
        "pending_leaves": pending_leaves,
        "open_attendance_sessions": open_attendance_sessions,
        "pending_reimbursement_queue": pending_reimbursement_queue,
        "pending_accounts_request_queue": pending_accounts_request_queue,
        "pending_loan_queue": pending_loan_queue,
        "total_pending_action_items": (
            pending_leaves
            + pending_reimbursement_queue
            + pending_accounts_request_queue
            + pending_loan_queue
        ),
    }

    return render_template("admin/dashboard.html", summary=summary)
 
 
# =====================================================
# EMPLOYEES LIST
# =====================================================
@admin_bp.route("/employees")
def employees():
    employees = Employee.query.order_by(cast(Employee.emp_code, Integer)).all()
    roles = (
        Role.query
        .filter(func.lower(Role.name).in_(["admin", "user", "account admin", "account_admin"]))
        .order_by(Role.name.asc())
        .all()
    )
    managers = (
        Employee.query
        .filter(Employee.status == "Active")
        .order_by(Employee.first_name.asc(), Employee.last_name.asc())
        .all()
    )

    summary = {
        "total_employees": len(employees),
        "active_employees": sum(1 for employee in employees if employee.status == "Active"),
        "managers": len(managers),
    }

    return render_template(
        "admin/employees.html",
        employees=employees,
        managers=managers,
        roles=roles,
        summary=summary,
    )
 
 
# =====================================================
# ADD EMPLOYEE
# =====================================================
@admin_bp.route("/employees/add", methods=["POST"])
def add_employee():
    try:
        # ---------- USER ----------
        user = User(
            email=request.form.get("work_email"),
            display_name=f"{request.form.get('first_name')} {request.form.get('last_name')}",
            role_id=int(request.form.get("role_id")),
            must_change_password=True,
            is_active=True  # ✅ IMPORTANT
        )
        user.set_password(request.form.get("password"))
        db.session.add(user)
        db.session.flush()
        manager_id=request.form.get("manager_id")
 
        # ---------- EMPLOYEE ----------
        emp = Employee(
            emp_code=request.form.get("emp_code"),
            first_name=request.form.get("first_name"),
            last_name=request.form.get("last_name"),
            work_email=request.form.get("work_email"),
            phone=request.form.get("phone"),
            department=request.form.get("department"),
            job_title=request.form.get("job_title"),
            date_of_joining=request.form.get("date_of_joining"),
            status="Active",
            user_id=user.id,
            manager_emp_id=int(manager_id) if manager_id else None
        )
        db.session.add(emp)
        db.session.flush()
 
        # ---------- SALARY ----------
        salary = EmployeeSalary(
            employee_id=emp.id,
            gross_salary=float(request.form.get("ctc", 0)),
            basic_percent=float(request.form.get("basic_percent", 50)),
            hra_percent=float(request.form.get("hra_percent", 20)),
            fixed_allowance=float(request.form.get("fixed_allowance", 4532)),
            medical_fixed=float(request.form.get("medical_fixed", 1000)),
            driver_reimbursement=float(request.form.get("driver_reimbursement", 1000)),
            epf_percent=float(request.form.get("epf_percent", 12)),
            total_deductions=0,
            net_salary=float(request.form.get("ctc", 0))
        )
        db.session.add(salary)
 
        # ---------- BANK ACCOUNT ----------
        account = EmployeeAccount(
            employee_id=emp.id,
            bank_name=request.form.get("bank_name"),
            account_number=request.form.get("account_number"),
            ifsc_code=request.form.get("ifsc_code"),
            account_holder_name=request.form.get("account_holder_name")
        )
        db.session.add(account)
 
        db.session.commit()
        flash("Employee added successfully", "success")
 
    except Exception as e:
        db.session.rollback()
        print(e)
        flash(str(e), "danger")
 
    return redirect(url_for("admin.employees"))
 
 
# =====================================================
# VIEW EMPLOYEE (JSON)
# =====================================================
@admin_bp.route("/employees/view/<int:id>")
def view_employee(id):
    emp = Employee.query.get_or_404(id)
    salary = EmployeeSalary.query.filter_by(employee_id=id).first()
    account = EmployeeAccount.query.filter_by(employee_id=id).first()
    normalized_role = normalize_role_name(emp.user.role.name if emp.user and emp.user.role else None)
 
    return jsonify({
        "emp_code": emp.emp_code,
        "first_name": emp.first_name,
        "last_name": emp.last_name,
        "work_email": emp.work_email,
        "phone": emp.phone,
        "department": emp.department,
        "job_title": emp.job_title,
        "date_of_joining": str(emp.date_of_joining),
        "status": emp.status,  # ✅ FIXED
        "role_id": get_role_id(normalized_role) if emp.user else None,
        "role_name": normalized_role.replace("_", " ").title() if normalized_role else "",
        "manager_id": emp.manager_emp_id,
        "manager_name": f"{emp.manager.first_name} {emp.manager.last_name}" if emp.manager else "-",
 
        "salary": {
            "gross_salary": salary.gross_salary if salary else 0,
            "basic_percent": salary.basic_percent if salary else 0,
            "hra_percent": salary.hra_percent if salary else 0,
            "fixed_allowance": salary.fixed_allowance if salary else 0,
            "medical_fixed": salary.medical_fixed if salary else 0,
            "driver_reimbursement": salary.driver_reimbursement if salary else 0,
            "epf_percent": salary.epf_percent if salary else 0
        },
 
        "account": {
            "bank_name": account.bank_name if account else "",
            "account_number": account.account_number if account else "",
            "ifsc_code": account.ifsc_code if account else "",
            "account_holder_name": account.account_holder_name if account else ""
        }
    })
 
 
# =====================================================
# EDIT EMPLOYEE
# =====================================================
@admin_bp.route("/employees/edit/<int:id>", methods=["POST"])
def edit_employee(id):
    emp = Employee.query.get_or_404(id)
 
    # ---------- BASIC ----------
    emp.first_name = request.form.get("first_name")
    emp.last_name = request.form.get("last_name")
    emp.work_email = request.form.get("work_email")
    emp.phone = request.form.get("phone")
    emp.department = request.form.get("department")
    emp.job_title = request.form.get("job_title")
    manager_id = request.form.get("manager_emp_id")
    emp.manager_emp_id = int(manager_id) if manager_id else None
 
    # 🔥 STATUS SYNC (MOST IMPORTANT PART)
    new_status = request.form.get("status")
    emp.status = new_status
 
    user = emp.user
    if user:
        user.email = emp.work_email
        user.display_name = f"{emp.first_name} {emp.last_name}".strip()
        user.role_id = int(request.form.get("role_id")) if request.form.get("role_id") else user.role_id
        if new_status == "Active":
            user.is_active = True
        else:
            user.is_active = False
 
    # ---------- SALARY ----------
    salary = EmployeeSalary.query.filter_by(employee_id=id).first()
    if not salary:
        salary = EmployeeSalary(employee_id=id)
        db.session.add(salary)
 
    salary.gross_salary = float(request.form.get("ctc", 0))
    salary.basic_percent = float(request.form.get("basic_percent", 50))
    salary.hra_percent = float(request.form.get("hra_percent", 20))
    salary.fixed_allowance = float(request.form.get("fixed_allowance", 4532))
    salary.medical_fixed = float(request.form.get("medical_fixed", 1000))
    salary.driver_reimbursement = float(request.form.get("driver_reimbursement", 1000))
    salary.epf_percent = float(request.form.get("epf_percent", 12))
    salary.net_salary = salary.gross_salary
 
    # ---------- ACCOUNT ----------
    account = EmployeeAccount.query.filter_by(employee_id=id).first()
    if not account:
        account = EmployeeAccount(employee_id=id)
        db.session.add(account)
 
    account.bank_name = request.form.get("bank_name")
    account.account_number = request.form.get("account_number")
    account.ifsc_code = request.form.get("ifsc_code")
    account.account_holder_name = request.form.get("account_holder_name")
 
    db.session.commit()
    flash("Employee updated successfully", "success")
    return redirect(url_for("admin.employees"))


# =====================================================
# USER ACCESS MANAGEMENT
# =====================================================
@admin_bp.route("/user-access")
def user_access():
    users = (
        User.query
        .outerjoin(Employee, Employee.user_id == User.id)
        .order_by(User.created_at.desc(), User.id.desc())
        .all()
    )
    roles = (
        Role.query
        .filter(func.lower(Role.name).in_(["admin", "user", "account admin", "account_admin"]))
        .order_by(Role.name.asc())
        .all()
    )
    admin_role_id = get_role_id(ROLE_ADMIN)
    user_role_id = get_role_id(ROLE_USER)
    account_admin_role_id = get_role_id(ROLE_ACCOUNT_ADMIN)

    summary = {
        "total_accounts": len(users),
        "active_accounts": sum(1 for user in users if user.is_active),
        "must_reset_password": sum(1 for user in users if user.must_change_password),
        "linked_employees": sum(1 for user in users if user.employee),
        "manager_access": sum(1 for user in users if has_manager_access(user=user, employee=user.employee)),
        "finance_accounts": sum(
            1 for user in users
            if normalize_role_name(user.role.name if user.role else None) == ROLE_ACCOUNT_ADMIN
        ),
    }

    return render_template(
        "admin/user_access.html",
        users=users,
        roles=roles,
        summary=summary,
        admin_role_id=admin_role_id,
        user_role_id=user_role_id,
        account_admin_role_id=account_admin_role_id,
    )


@admin_bp.route("/user-access/<int:user_id>/update", methods=["POST"])
def update_user_access(user_id):
    user = User.query.get_or_404(user_id)

    role_id = request.form.get("role_id")
    is_active = request.form.get("is_active") == "true"
    must_change_password = request.form.get("must_change_password") == "true"
    reset_password = request.form.get("reset_password") == "true"

    if role_id:
        user.role_id = int(role_id)

    user.is_active = is_active
    user.must_change_password = must_change_password

    if user.employee:
        user.employee.status = "Active" if is_active else "Inactive"

    if reset_password:
        temp_password = request.form.get("temp_password") or "Temp@123"
        user.set_password(temp_password)
        user.must_change_password = True

    db.session.commit()
    flash("User access updated successfully.", "success")
    return redirect(url_for("admin.user_access"))


@admin_bp.route("/email-configuration", methods=["GET", "POST"])
def email_configuration():
    config = get_email_delivery_config()

    if request.method == "POST":
        delivery_mode = request.form.get("delivery_mode", DELIVERY_INTENDED)
        test_address = (request.form.get("test_address") or "").strip() or None

        if delivery_mode == DELIVERY_TEST and not test_address:
            flash("Test address is required when test routing is selected.", "danger")
            return redirect(url_for("admin.email_configuration"))

        config.delivery_mode = delivery_mode
        config.test_address = test_address
        db.session.commit()
        flash("Email configuration updated successfully.", "success")
        return redirect(url_for("admin.email_configuration"))

    return render_template(
        "admin/email_configuration.html",
        config=config,
        delivery_intended=DELIVERY_INTENDED,
        delivery_test=DELIVERY_TEST,
    )
 
 
# =====================================================
# CONFIGURE LEAVE APPROVALS
# =====================================================
@admin_bp.route("/configure-approvals", methods=["GET", "POST"])
def configure_approvals():
    users = User.query.all()
    config = LeaveApprovalConfig.query.first()
 
    if not config:
        config = LeaveApprovalConfig()
        db.session.add(config)
        db.session.commit()
 
    if request.method == "POST":
        level1 = request.form.get("level1")
        level2 = request.form.get("level2")
 
        if level1 == "MANAGER":
            config.use_manager_l1 = True
            config.level1_approver_id = None
        else:
            config.use_manager_l1 = False
            config.level1_approver_id = int(level1) if level1 else None
 
        config.level2_approver_id = int(level2) if level2 else None
 
        db.session.commit()
        flash("Approval workflow updated successfully!", "success")
        return redirect(url_for("admin.configure_approvals"))
 
    return render_template(
        "admin/configure_approvals.html",
        users=users,
        config=config
    )
 
 
