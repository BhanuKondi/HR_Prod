from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import (
    Employee,
    EmployeeSalary,
    PayrollRun,
    SalaryRevisionAction,
    SalaryRevisionConfig,
    SalaryRevisionRequest,
    User,
)
from utils.authz import ROLE_ACCOUNT_ADMIN, ROLE_ADMIN, ROLE_USER, get_current_role, get_current_user, require_roles


admin_salary_revisions_bp = Blueprint(
    "admin_salary_revisions",
    __name__,
    url_prefix="/admin/salary-revisions",
)

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_APPLIED = "applied"


@admin_salary_revisions_bp.before_request
def enforce_admin_role():
    return require_roles(ROLE_ADMIN, ROLE_ACCOUNT_ADMIN, ROLE_USER)


def is_admin_user() -> bool:
    return get_current_role() == ROLE_ADMIN


def get_or_create_config() -> SalaryRevisionConfig:
    config = SalaryRevisionConfig.query.order_by(SalaryRevisionConfig.id.asc()).first()
    if config:
        return config
    config = SalaryRevisionConfig()
    db.session.add(config)
    db.session.commit()
    return config


def generate_revision_no() -> str:
    prefix = datetime.utcnow().strftime("SRV-%Y%m%d")
    count_today = SalaryRevisionRequest.query.filter(
        SalaryRevisionRequest.revision_no.like(f"{prefix}-%")
    ).count()
    return f"{prefix}-{count_today + 1:04d}"


def salary_snapshot(salary: EmployeeSalary) -> dict:
    return {
        "gross_salary": float(salary.gross_salary or 0),
        "basic_percent": float(salary.basic_percent or 0),
        "hra_percent": float(salary.hra_percent or 0),
        "fixed_allowance": float(salary.fixed_allowance or 0),
        "medical_fixed": float(salary.medical_fixed or 0),
        "driver_reimbursement": float(salary.driver_reimbursement or 0),
        "epf_percent": float(salary.epf_percent or 0),
    }


def parse_effective_month(raw: str | None) -> date:
    if not raw:
        raise ValueError("Effective month is required.")
    try:
        year, month = map(int, raw.split("-"))
        return date(year, month, 1)
    except Exception as exc:
        raise ValueError("Effective month is invalid.") from exc


def add_action(revision: SalaryRevisionRequest, user_id: int, action_type: str, from_status: str | None, to_status: str, comments: str | None = None):
    db.session.add(
        SalaryRevisionAction(
            salary_revision_request_id=revision.id,
            action_by_user_id=user_id,
            action_type=action_type,
            from_status=from_status,
            to_status=to_status,
            comments=comments,
        )
    )


@admin_salary_revisions_bp.route("")
def list_revisions():
    if not is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("auth.login"))
    status_filter = (request.args.get("status_filter") or "pending").strip().lower()
    allowed = {"pending", "approved", "rejected", "applied", "draft", "all"}
    if status_filter not in allowed:
        status_filter = "pending"

    base_query = SalaryRevisionRequest.query
    if status_filter == "pending":
        base_query = base_query.filter_by(status=STATUS_PENDING)
    elif status_filter == "approved":
        base_query = base_query.filter_by(status=STATUS_APPROVED)
    elif status_filter == "rejected":
        base_query = base_query.filter_by(status=STATUS_REJECTED)
    elif status_filter == "applied":
        base_query = base_query.filter_by(status=STATUS_APPLIED)
    elif status_filter == "draft":
        base_query = base_query.filter_by(status=STATUS_DRAFT)

    revisions = base_query.order_by(SalaryRevisionRequest.created_at.desc()).all()
    all_rows = SalaryRevisionRequest.query.all()
    summary = {
        "pending": sum(1 for row in all_rows if row.status == STATUS_PENDING),
        "approved": sum(1 for row in all_rows if row.status == STATUS_APPROVED),
        "rejected": sum(1 for row in all_rows if row.status == STATUS_REJECTED),
        "all": len(all_rows),
    }
    return render_template(
        "admin/salary_revisions.html",
        revisions=revisions,
        summary=summary,
        status_filter=status_filter,
    )


@admin_salary_revisions_bp.route("/new", methods=["GET", "POST"])
def new_revision():
    if not is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("auth.login"))
    employees = Employee.query.filter(Employee.status == "Active").order_by(Employee.first_name.asc(), Employee.last_name.asc()).all()
    config = get_or_create_config()
    current_user = get_current_user()

    if request.method == "POST":
        try:
            employee_id = int(request.form.get("employee_id") or 0)
            employee = Employee.query.get(employee_id)
            if not employee:
                raise ValueError("Please choose a valid employee.")
            salary = EmployeeSalary.query.filter_by(employee_id=employee.id).first()
            if not salary:
                raise ValueError("Employee salary record is not available.")

            effective_from = parse_effective_month(request.form.get("effective_from_month"))
            reason = (request.form.get("reason") or "").strip()
            if not reason:
                raise ValueError("Reason is required.")

            proposed = {
                "gross_salary": float(request.form.get("gross_salary") or 0),
                "basic_percent": float(request.form.get("basic_percent") or 0),
                "hra_percent": float(request.form.get("hra_percent") or 0),
                "fixed_allowance": float(request.form.get("fixed_allowance") or 0),
                "medical_fixed": float(request.form.get("medical_fixed") or 0),
                "driver_reimbursement": float(request.form.get("driver_reimbursement") or 0),
                "epf_percent": float(request.form.get("epf_percent") or 0),
            }
            if proposed["gross_salary"] <= 0:
                raise ValueError("Gross salary must be greater than zero.")

            submit_now = (request.form.get("form_action") or "draft") == "submit"
            approver_user_id = config.fixed_approver_user_id if submit_now else None
            if submit_now and not approver_user_id:
                raise ValueError("Configure fixed approver before submitting revision.")

            status = STATUS_PENDING if submit_now else STATUS_DRAFT
            revision = SalaryRevisionRequest(
                revision_no=generate_revision_no(),
                employee_id=employee.id,
                requested_by_user_id=current_user.id,
                approver_user_id=approver_user_id,
                effective_from=effective_from,
                reason=reason,
                status=status,
                current_salary_json=salary_snapshot(salary),
                proposed_salary_json=proposed,
                submitted_at=datetime.utcnow() if submit_now else None,
            )
            db.session.add(revision)
            db.session.flush()
            add_action(
                revision=revision,
                user_id=current_user.id,
                action_type="submitted" if submit_now else "created",
                from_status=None,
                to_status=status,
                comments=reason,
            )
            db.session.commit()
            flash("Salary revision submitted." if submit_now else "Salary revision draft saved.", "success")
            return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))
        except Exception as exc:
            db.session.rollback()
            flash(str(exc), "danger")

    return render_template(
        "admin/salary_revision_form.html",
        employees=employees,
    )


@admin_salary_revisions_bp.route("/<int:revision_id>")
def view_revision(revision_id):
    revision = SalaryRevisionRequest.query.get_or_404(revision_id)
    current_user = get_current_user()
    if not is_admin_user() and revision.approver_user_id != current_user.id:
        flash("This revision is not assigned to you.", "danger")
        return redirect(url_for("auth.login"))
    can_review = revision.status == STATUS_PENDING and revision.approver_user_id == current_user.id
    can_apply = revision.status == STATUS_APPROVED
    return render_template(
        "admin/salary_revision_detail.html",
        revision=revision,
        can_review=can_review,
        can_apply=can_apply,
    )


@admin_salary_revisions_bp.route("/<int:revision_id>/approve", methods=["POST"])
def approve_revision(revision_id):
    revision = SalaryRevisionRequest.query.get_or_404(revision_id)
    current_user = get_current_user()
    if revision.status != STATUS_PENDING:
        flash("Only pending revisions can be approved.", "warning")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))
    if revision.approver_user_id != current_user.id:
        flash("This revision is not assigned to you for approval.", "danger")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))

    comments = (request.form.get("comments") or "").strip() or None
    from_status = revision.status
    revision.status = STATUS_APPROVED
    revision.approver_comments = comments
    revision.approved_at = datetime.utcnow()
    add_action(revision, current_user.id, "approved", from_status, STATUS_APPROVED, comments)
    db.session.commit()
    flash("Salary revision approved.", "success")
    return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))


@admin_salary_revisions_bp.route("/<int:revision_id>/reject", methods=["POST"])
def reject_revision(revision_id):
    revision = SalaryRevisionRequest.query.get_or_404(revision_id)
    current_user = get_current_user()
    if revision.status != STATUS_PENDING:
        flash("Only pending revisions can be rejected.", "warning")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))
    if revision.approver_user_id != current_user.id:
        flash("This revision is not assigned to you for approval.", "danger")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))

    comments = (request.form.get("comments") or "").strip()
    if not comments:
        flash("Comments are required when rejecting revision.", "danger")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))
    from_status = revision.status
    revision.status = STATUS_REJECTED
    revision.approver_comments = comments
    revision.rejected_at = datetime.utcnow()
    add_action(revision, current_user.id, "rejected", from_status, STATUS_REJECTED, comments)
    db.session.commit()
    flash("Salary revision rejected.", "success")
    return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))


@admin_salary_revisions_bp.route("/<int:revision_id>/apply", methods=["POST"])
def apply_revision(revision_id):
    if not is_admin_user():
        flash("Only HR/Admin can apply revision.", "danger")
        return redirect(url_for("auth.login"))
    revision = SalaryRevisionRequest.query.get_or_404(revision_id)
    if revision.status != STATUS_APPROVED:
        flash("Only approved revisions can be applied.", "warning")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))

    payrun = PayrollRun.query.filter_by(month=revision.effective_from.month, year=revision.effective_from.year).first()
    if payrun and payrun.approved:
        flash("Payroll is already approved for the effective month. Revision cannot be applied.", "danger")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))

    salary = EmployeeSalary.query.filter_by(employee_id=revision.employee_id).first()
    if not salary:
        flash("Employee salary record missing.", "danger")
        return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))

    proposed = revision.proposed_salary_json or {}
    salary.gross_salary = float(proposed.get("gross_salary") or salary.gross_salary)
    salary.basic_percent = float(proposed.get("basic_percent") or salary.basic_percent)
    salary.hra_percent = float(proposed.get("hra_percent") or salary.hra_percent)
    salary.fixed_allowance = float(proposed.get("fixed_allowance") or salary.fixed_allowance)
    salary.medical_fixed = float(proposed.get("medical_fixed") or salary.medical_fixed)
    salary.driver_reimbursement = float(proposed.get("driver_reimbursement") or salary.driver_reimbursement)
    salary.epf_percent = float(proposed.get("epf_percent") or salary.epf_percent)
    salary.net_salary = salary.gross_salary

    from_status = revision.status
    revision.status = STATUS_APPLIED
    revision.applied_at = datetime.utcnow()
    add_action(revision, get_current_user().id, "applied", from_status, STATUS_APPLIED, "Applied to active salary.")
    db.session.commit()
    flash("Salary revision applied to employee salary.", "success")
    return redirect(url_for("admin_salary_revisions.view_revision", revision_id=revision.id))


@admin_salary_revisions_bp.route("/settings", methods=["GET", "POST"])
def settings():
    if not is_admin_user():
        flash("Access denied.", "danger")
        return redirect(url_for("auth.login"))
    config = get_or_create_config()
    users = User.query.filter_by(is_active=True).order_by(User.display_name.asc(), User.email.asc()).all()
    if request.method == "POST":
        approver_user_id = request.form.get("fixed_approver_user_id")
        config.fixed_approver_user_id = int(approver_user_id) if approver_user_id else None
        db.session.commit()
        flash("Salary revision approver configured.", "success")
        return redirect(url_for("admin_salary_revisions.settings"))
    return render_template("admin/salary_revision_settings.html", config=config, users=users)
