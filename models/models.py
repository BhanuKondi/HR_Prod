from datetime import datetime
from .db import db
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.dialects.mysql import INTEGER, BIGINT, VARCHAR, TEXT
import uuid

# ------------------- Roles -------------------
class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(INTEGER, primary_key=True)
    name = db.Column(VARCHAR(100), unique=True, nullable=False)


class Company(db.Model):
    __tablename__ = "companies"

    id = db.Column(INTEGER, primary_key=True)
    code = db.Column(VARCHAR(50), unique=True, nullable=False)
    display_name = db.Column(VARCHAR(150), nullable=False)
    legal_name = db.Column(VARCHAR(255), nullable=False)
    gst_number = db.Column(VARCHAR(50), nullable=False)
    address = db.Column(TEXT, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ------------------- Users -------------------
class User(db.Model):
    __tablename__ = "users"
    id = db.Column(INTEGER, primary_key=True)
    email = db.Column(VARCHAR(255), unique=True, nullable=False)
    password_hash = db.Column(VARCHAR(255), nullable=False)
    display_name = db.Column(VARCHAR(255))
    profile_photo_path = db.Column(VARCHAR(255), nullable=True)

    role_id = db.Column(INTEGER, db.ForeignKey("roles.id"), nullable=False)
    role = db.relationship("Role")

    is_active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # 1-to-1 Employee Profile
    employee = db.relationship("Employee", back_populates="user", uselist=False)

    # 👇 ADD THIS: Link Attendance to User
    attendance_records = db.relationship("Attendance", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# ------------------- Employees -------------------
class Employee(db.Model):
    __tablename__ = "employees"
    id = db.Column(INTEGER, primary_key=True)
    emp_code = db.Column(VARCHAR(50), unique=True, nullable=False)

    user_id = db.Column(INTEGER, db.ForeignKey("users.id"))
    user = db.relationship("User", back_populates="employee")

    first_name = db.Column(VARCHAR(100), nullable=False)
    last_name = db.Column(VARCHAR(100), nullable=False)
    work_email = db.Column(VARCHAR(255), unique=True, nullable=False)
    phone = db.Column(VARCHAR(20))
    address = db.Column(TEXT)
    date_of_joining = db.Column(db.Date, nullable=False)

    manager_emp_id = db.Column(INTEGER, db.ForeignKey("employees.id"))
    manager = db.relationship(
    "Employee",
    remote_side=[id],
    backref="team_members"
)

    status = db.Column(VARCHAR(50), default="Active")
    department = db.Column(VARCHAR(100))
    job_title = db.Column(VARCHAR(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    salary = db.relationship("EmployeeSalary", backref="employee", uselist=False)
    account = db.relationship("EmployeeAccount", backref="employee", uselist=False)

    # 👇 OPTIONAL — only if you want attendance per employee also
    #attendance_records = db.relationship("Attendance", backref="employee", lazy=True)


# ------------------- Leave Types -------------------

# ------------------- Leaves -------------------
class Leave(db.Model):
    __tablename__ = "leaves"

    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(50), db.ForeignKey("employees.emp_code"), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    # models/models.py

    total_days = db.Column(db.Float)  
# OR (recommended)
# total_days = db.Column(db.Numeric(3,1))
    reason = db.Column(db.String(200))
    status = db.Column(db.String(20), default="Pending")
    decision_date = db.Column(db.DateTime)

    employee = db.relationship("Employee", backref="leaves", foreign_keys=[emp_code])

class Holiday(db.Model):
    __tablename__ = "holidays" 
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    day = db.Column(db.String(20))
    occasion = db.Column(db.String(100))

class LeaveApprovalConfig(db.Model):
    __tablename__ = "leave_approval_config"

    id = db.Column(db.Integer, primary_key=True)
    level1_approver_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    level2_approver_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    use_manager_l1 = db.Column(db.Boolean, default=False)
class Leavee(db.Model):
    __tablename__ = 'employee_leaves'
    id = db.Column(db.Integer, primary_key=True)
    emp_code = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    total_days = db.Column(db.Float, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    employee_name = db.Column(db.String(45), nullable=False)
    status = db.Column(db.String(20), default="PENDING_L1")  # PENDING_L1, REJECTED_L1, PENDING_L2, APPROVED
    level1_approver_id = db.Column(db.Integer, nullable=True)
    level2_approver_id = db.Column(db.Integer, nullable=True)
    current_approver_id = db.Column(db.Integer, nullable=True)
    level1_decision_date = db.Column(db.DateTime, nullable=True)
    level2_decision_date = db.Column(db.DateTime, nullable=True)
    leave_type = db.Column(db.String(30), nullable=False)  # Casual Leave, Sick Leave, Leave Without Pay


class EmployeeSalary(db.Model):
    __tablename__ = "employee_salary"
 
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), unique=True)
 
    # Earnings
    basic_percent = db.Column(db.Float, default=50)
    hra_percent = db.Column(db.Float, default=20)
    fixed_allowance = db.Column(db.Float, default=4532)
 
    # Reimbursements
    medical_fixed = db.Column(db.Float, default=1000)
    driver_reimbursement = db.Column(db.Float, default=1000)
 
    # Deductions
    epf_percent = db.Column(db.Float, default=12)
 
    # Salary totals
    gross_salary = db.Column(db.Float, nullable=False)
    total_deductions = db.Column(db.Float, default=0)
    net_salary = db.Column(db.Float, nullable=False)
 
    created_at = db.Column(db.DateTime, server_default=db.func.now())
 
 
# ------------------- Employee Bank Account -----------------
class EmployeeAccount(db.Model):
    __tablename__ = "employee_account"
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), unique=True)
    bank_name = db.Column(db.String(100))
    account_number = db.Column(db.String(30))
    ifsc_code = db.Column(db.String(15))
    account_holder_name = db.Column(db.String(100))
class PayrollRun(db.Model):
    __tablename__ = "payroll_run"

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)

    approved = db.Column(db.Boolean, default=False)
    approved_at = db.Column(db.DateTime)

    __table_args__ = (
        db.UniqueConstraint('month', 'year', name='uq_payroll_run_month_year'),
    )
class PayrollDetails(db.Model):
    __tablename__ = "payroll_details"
 
    id = db.Column(db.Integer, primary_key=True)
 
    employee_id = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
 
    net_salary = db.Column(db.Float, nullable=False)
    bonus = db.Column(db.Float, default=0)
    deduction = db.Column(db.Float, default=0)
    final_salary = db.Column(db.Float, nullable=False)
    comments = db.Column(db.String(255), nullable=True)  # ✅ NEW FIELD

 
    created_at = db.Column(db.DateTime, server_default=db.func.now())
 
    __table_args__ = (
        db.UniqueConstraint('employee_id', 'month', 'year', name='uq_emp_month_year'),
    )


class SalaryRevisionConfig(db.Model):
    __tablename__ = "salary_revision_config"

    id = db.Column(db.Integer, primary_key=True)
    fixed_approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    fixed_approver = db.relationship("User", foreign_keys=[fixed_approver_user_id])


class SalaryRevisionRequest(db.Model):
    __tablename__ = "salary_revision_requests"

    id = db.Column(db.Integer, primary_key=True)
    revision_no = db.Column(db.String(30), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    effective_from = db.Column(db.Date, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="draft")
    current_salary_json = db.Column(db.JSON, nullable=False)
    proposed_salary_json = db.Column(db.JSON, nullable=False)
    approver_comments = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    rejected_at = db.Column(db.DateTime, nullable=True)
    applied_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    employee = db.relationship("Employee", foreign_keys=[employee_id])
    requested_by = db.relationship("User", foreign_keys=[requested_by_user_id])
    approver = db.relationship("User", foreign_keys=[approver_user_id])


class SalaryRevisionAction(db.Model):
    __tablename__ = "salary_revision_actions"

    id = db.Column(db.Integer, primary_key=True)
    salary_revision_request_id = db.Column(db.Integer, db.ForeignKey("salary_revision_requests.id"), nullable=False)
    action_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_type = db.Column(db.String(30), nullable=False)
    from_status = db.Column(db.String(30), nullable=True)
    to_status = db.Column(db.String(30), nullable=False)
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    revision = db.relationship(
        "SalaryRevisionRequest",
        foreign_keys=[salary_revision_request_id],
        backref=db.backref("actions", cascade="all, delete-orphan", lazy=True),
    )
    action_by = db.relationship("User", foreign_keys=[action_by_user_id])


class ReimbursementType(db.Model):
    __tablename__ = "reimbursement_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class ReimbursementConfig(db.Model):
    __tablename__ = "reimbursement_config"

    id = db.Column(db.Integer, primary_key=True)
    approver_mode = db.Column(db.String(30), nullable=False, default="reporting_manager")
    fixed_approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    allow_partial_approval = db.Column(db.Boolean, default=True, nullable=False)
    allow_multiple_attachments = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    fixed_approver = db.relationship("User", foreign_keys=[fixed_approver_user_id])


class ReimbursementRequest(db.Model):
    __tablename__ = "reimbursement_requests"

    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(30), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    reimbursement_type_id = db.Column(db.Integer, db.ForeignKey("reimbursement_types.id"), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    bill_date = db.Column(db.Date, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    description = db.Column(db.Text, nullable=False)
    requested_amount = db.Column(db.Numeric(12, 2), nullable=False)
    manager_approved_amount = db.Column(db.Numeric(12, 2), nullable=True)
    finance_approved_amount = db.Column(db.Numeric(12, 2), nullable=True)
    final_amount = db.Column(db.Numeric(12, 2), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="draft")
    manager_approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    finance_approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    current_assignee_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    manager_comments = db.Column(db.Text, nullable=True)
    finance_comments = db.Column(db.Text, nullable=True)
    payment_reference = db.Column(db.String(100), nullable=True)
    payment_date = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    employee = db.relationship("Employee", foreign_keys=[employee_id], backref="reimbursement_requests")
    reimbursement_type = db.relationship("ReimbursementType", foreign_keys=[reimbursement_type_id])
    company = db.relationship("Company", foreign_keys=[company_id])
    manager_approver = db.relationship("User", foreign_keys=[manager_approver_user_id])
    finance_approver = db.relationship("User", foreign_keys=[finance_approver_user_id])
    current_assignee = db.relationship("User", foreign_keys=[current_assignee_user_id])


class ReimbursementAttachment(db.Model):
    __tablename__ = "reimbursement_attachments"

    id = db.Column(db.Integer, primary_key=True)
    reimbursement_request_id = db.Column(db.Integer, db.ForeignKey("reimbursement_requests.id"), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    uploaded_at = db.Column(db.DateTime, server_default=db.func.now())

    reimbursement_request = db.relationship(
        "ReimbursementRequest",
        foreign_keys=[reimbursement_request_id],
        backref=db.backref("attachments", cascade="all, delete-orphan", lazy=True),
    )


class ReimbursementAction(db.Model):
    __tablename__ = "reimbursement_actions"

    id = db.Column(db.Integer, primary_key=True)
    reimbursement_request_id = db.Column(db.Integer, db.ForeignKey("reimbursement_requests.id"), nullable=False)
    action_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_type = db.Column(db.String(40), nullable=False)
    from_status = db.Column(db.String(40), nullable=True)
    to_status = db.Column(db.String(40), nullable=False)
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    reimbursement_request = db.relationship(
        "ReimbursementRequest",
        foreign_keys=[reimbursement_request_id],
        backref=db.backref("actions", cascade="all, delete-orphan", lazy=True),
    )
    action_by = db.relationship("User", foreign_keys=[action_by_user_id])


class AccountsRequestType(db.Model):
    __tablename__ = "accounts_request_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class AccountsRequestConfig(db.Model):
    __tablename__ = "accounts_request_config"

    id = db.Column(db.Integer, primary_key=True)
    default_approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    allow_partial_approval = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    default_approver = db.relationship("User", foreign_keys=[default_approver_user_id])


class AccountsRequest(db.Model):
    __tablename__ = "accounts_requests"

    id = db.Column(db.Integer, primary_key=True)
    request_no = db.Column(db.String(30), unique=True, nullable=False)
    request_type_id = db.Column(db.Integer, db.ForeignKey("accounts_request_types.id"), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=False)
    requested_amount = db.Column(db.Numeric(12, 2), nullable=False)
    approved_amount = db.Column(db.Numeric(12, 2), nullable=True)
    actual_amount = db.Column(db.Numeric(12, 2), nullable=True)
    payment_mode = db.Column(db.String(30), nullable=True)
    vendor_name = db.Column(db.String(150), nullable=True)
    payment_reference = db.Column(db.String(100), nullable=True)
    payment_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="draft")
    approval_comments = db.Column(db.Text, nullable=True)
    execution_comments = db.Column(db.Text, nullable=True)
    closure_comments = db.Column(db.Text, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    expense_recorded_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    request_type = db.relationship("AccountsRequestType", foreign_keys=[request_type_id])
    company = db.relationship("Company", foreign_keys=[company_id])
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    approver = db.relationship("User", foreign_keys=[approver_user_id])


class AccountsRequestAttachment(db.Model):
    __tablename__ = "accounts_request_attachments"

    id = db.Column(db.Integer, primary_key=True)
    accounts_request_id = db.Column(db.Integer, db.ForeignKey("accounts_requests.id"), nullable=False)
    attachment_stage = db.Column(db.String(30), nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(100), nullable=True)
    uploaded_at = db.Column(db.DateTime, server_default=db.func.now())

    accounts_request = db.relationship(
        "AccountsRequest",
        foreign_keys=[accounts_request_id],
        backref=db.backref("attachments", cascade="all, delete-orphan", lazy=True),
    )


class AccountsRequestAction(db.Model):
    __tablename__ = "accounts_request_actions"

    id = db.Column(db.Integer, primary_key=True)
    accounts_request_id = db.Column(db.Integer, db.ForeignKey("accounts_requests.id"), nullable=False)
    action_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_type = db.Column(db.String(40), nullable=False)
    from_status = db.Column(db.String(40), nullable=True)
    to_status = db.Column(db.String(40), nullable=False)
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    accounts_request = db.relationship(
        "AccountsRequest",
        foreign_keys=[accounts_request_id],
        backref=db.backref("actions", cascade="all, delete-orphan", lazy=True),
    )
    action_by = db.relationship("User", foreign_keys=[action_by_user_id])


class EmployeeLoanConfig(db.Model):
    __tablename__ = "employee_loan_config"

    id = db.Column(db.Integer, primary_key=True)
    fixed_approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    fixed_approver = db.relationship("User", foreign_keys=[fixed_approver_user_id])


class EmployeeLoan(db.Model):
    __tablename__ = "employee_loans"

    id = db.Column(db.Integer, primary_key=True)
    loan_no = db.Column(db.String(30), unique=True, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    requested_amount = db.Column(db.Numeric(12, 2), nullable=False)
    approved_amount = db.Column(db.Numeric(12, 2), nullable=True)
    total_installments = db.Column(db.Integer, nullable=False)
    monthly_installment = db.Column(db.Numeric(12, 2), nullable=True)
    reason = db.Column(db.Text, nullable=False)
    repayment_notes = db.Column(db.Text, nullable=True)
    preferred_disbursement_date = db.Column(db.Date, nullable=True)
    repayment_start_month = db.Column(db.Integer, nullable=True)
    repayment_start_year = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(40), nullable=False, default="draft")
    approver_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    account_admin_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    current_assignee_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approval_comments = db.Column(db.Text, nullable=True)
    finance_comments = db.Column(db.Text, nullable=True)
    payment_reference = db.Column(db.String(100), nullable=True)
    payment_date = db.Column(db.Date, nullable=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    paid_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    employee = db.relationship("Employee", foreign_keys=[employee_id], backref="loan_requests")
    approver = db.relationship("User", foreign_keys=[approver_user_id])
    account_admin = db.relationship("User", foreign_keys=[account_admin_user_id])
    current_assignee = db.relationship("User", foreign_keys=[current_assignee_user_id])


class EmployeeLoanAction(db.Model):
    __tablename__ = "employee_loan_actions"

    id = db.Column(db.Integer, primary_key=True)
    employee_loan_id = db.Column(db.Integer, db.ForeignKey("employee_loans.id"), nullable=False)
    action_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action_type = db.Column(db.String(40), nullable=False)
    from_status = db.Column(db.String(40), nullable=True)
    to_status = db.Column(db.String(40), nullable=False)
    comments = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    employee_loan = db.relationship(
        "EmployeeLoan",
        foreign_keys=[employee_loan_id],
        backref=db.backref("actions", cascade="all, delete-orphan", lazy=True),
    )
    action_by = db.relationship("User", foreign_keys=[action_by_user_id])


class EmployeeLoanRepayment(db.Model):
    __tablename__ = "employee_loan_repayments"

    id = db.Column(db.Integer, primary_key=True)
    employee_loan_id = db.Column(db.Integer, db.ForeignKey("employee_loans.id"), nullable=False)
    payroll_month = db.Column(db.Integer, nullable=False)
    payroll_year = db.Column(db.Integer, nullable=False)
    installment_number = db.Column(db.Integer, nullable=False)
    deducted_amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    employee_loan = db.relationship(
        "EmployeeLoan",
        foreign_keys=[employee_loan_id],
        backref=db.backref("repayments", cascade="all, delete-orphan", lazy=True),
    )

    __table_args__ = (
        db.UniqueConstraint("employee_loan_id", "payroll_month", "payroll_year", name="uq_employee_loan_payroll_month"),
    )


class EmailDeliveryConfig(db.Model):
    __tablename__ = "email_delivery_config"

    id = db.Column(db.Integer, primary_key=True)
    delivery_mode = db.Column(db.String(30), nullable=False, default="intended_recipients")
    test_address = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

from models.attendance import Attendance
