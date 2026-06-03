from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import EmployeeLoan
from utils.authz import (
    ROLE_ACCOUNT_ADMIN,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_USER,
    get_base_template_for_role,
    get_current_employee,
    get_current_role,
    require_roles,
)
from utils.loan_service import (
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_PAID,
    STATUS_PENDING_APPROVAL,
    STATUS_PENDING_PAYMENT,
    generate_loan_no,
    get_or_create_loan_config,
    parse_amount,
    parse_installments,
    parse_optional_date,
    record_action,
    require_fixed_approver,
    summarize_employee_loans,
)
from utils.route_guards import require_employee_or_redirect, require_owned_resource_or_redirect
from utils.workflow_email_service import send_loan_submitted_email


employee_loans_bp = Blueprint("employee_loans", __name__, url_prefix="/employee/loans")


@employee_loans_bp.before_request
def enforce_access():
    return require_roles(ROLE_USER, ROLE_MANAGER, ROLE_ADMIN, ROLE_ACCOUNT_ADMIN)


@employee_loans_bp.route("")
def list_loans():
    employee = get_current_employee()
    base_template = get_base_template_for_role(get_current_role())
    if not employee:
        flash("A linked employee profile is required to use employee loans.", "warning")
        return render_template(
            "employee/loans.html",
            base_template=base_template,
            employee=None,
            loans=[],
            summary={"draft": 0, "pending": 0, "active": 0, "completed": 0},
        )

    loans = (
        EmployeeLoan.query.filter_by(employee_id=employee.id)
        .order_by(EmployeeLoan.created_at.desc(), EmployeeLoan.id.desc())
        .all()
    )
    summary = summarize_employee_loans(loans)
    return render_template(
        "employee/loans.html",
        base_template=base_template,
        employee=employee,
        loans=loans,
        summary=summary,
    )


@employee_loans_bp.route("/new")
def new_loan():
    employee, error_response = require_employee_or_redirect(
        get_employee_fn=get_current_employee,
        redirect_endpoint="employee_loans.list_loans",
        message="A linked employee profile is required to request a loan.",
        category="warning",
    )
    if error_response:
        return error_response
    return render_template(
        "employee/loan_form.html",
        base_template=get_base_template_for_role(get_current_role()),
        config=get_or_create_loan_config(),
    )


@employee_loans_bp.route("/create", methods=["POST"])
def create_loan():
    employee, error_response = require_employee_or_redirect(
        get_employee_fn=get_current_employee,
        redirect_endpoint="employee_loans.list_loans",
        message="A linked employee profile is required to request a loan.",
        category="danger",
    )
    if error_response:
        return error_response

    try:
        requested_amount = parse_amount(request.form.get("requested_amount"))
        total_installments = parse_installments(request.form.get("total_installments"))
        reason = (request.form.get("reason") or "").strip()
        repayment_notes = (request.form.get("repayment_notes") or "").strip() or None
        preferred_disbursement_date = parse_optional_date(request.form.get("preferred_disbursement_date"))
        if not reason:
            raise ValueError("Reason is required.")

        config = get_or_create_loan_config()
        approver = require_fixed_approver(config)
        action = request.form.get("form_action", "draft")
        status = STATUS_DRAFT
        submitted_at = None
        current_assignee_user_id = None
        if action == "submit":
            status = STATUS_PENDING_APPROVAL
            submitted_at = datetime.utcnow()
            current_assignee_user_id = approver.id

        loan = EmployeeLoan(
            loan_no=generate_loan_no(),
            employee_id=employee.id,
            requested_amount=requested_amount,
            total_installments=total_installments,
            reason=reason,
            repayment_notes=repayment_notes,
            preferred_disbursement_date=preferred_disbursement_date,
            approver_user_id=approver.id,
            current_assignee_user_id=current_assignee_user_id,
            status=status,
            submitted_at=submitted_at,
        )
        db.session.add(loan)
        db.session.flush()
        record_action(
            loan=loan,
            action_by_user_id=employee.user_id,
            action_type="submitted" if status == STATUS_PENDING_APPROVAL else "created",
            from_status=None,
            to_status=status,
        )
        db.session.commit()
        if status == STATUS_PENDING_APPROVAL:
            send_loan_submitted_email(loan)
        flash(
            "Loan request submitted for approval." if status == STATUS_PENDING_APPROVAL else "Loan request draft saved.",
            "success",
        )
        return redirect(url_for("employee_loans.view_loan", loan_id=loan.id))
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("employee_loans.new_loan"))


@employee_loans_bp.route("/<int:loan_id>")
def view_loan(loan_id):
    employee, error_response = require_employee_or_redirect(
        get_employee_fn=get_current_employee,
        redirect_endpoint="employee_loans.list_loans",
        message="A linked employee profile is required to view employee loans.",
        category="warning",
    )
    if error_response:
        return error_response
    loan = EmployeeLoan.query.get_or_404(loan_id)
    loan, error_response = require_owned_resource_or_redirect(
        resource=loan,
        owner_id=employee.id,
        resource_label="employee_id",
        action_label="view",
        redirect_endpoint="employee_loans.list_loans",
    )
    if error_response:
        return error_response
    return render_template(
        "employee/loan_detail.html",
        base_template=get_base_template_for_role(get_current_role()),
        loan=loan,
        can_submit=loan.status == STATUS_DRAFT,
    )


@employee_loans_bp.route("/<int:loan_id>/submit", methods=["POST"])
def submit_loan(loan_id):
    employee, error_response = require_employee_or_redirect(
        get_employee_fn=get_current_employee,
        redirect_endpoint="employee_loans.list_loans",
        message="A linked employee profile is required to submit employee loans.",
        category="danger",
    )
    if error_response:
        return error_response
    loan = EmployeeLoan.query.get_or_404(loan_id)
    loan, error_response = require_owned_resource_or_redirect(
        resource=loan,
        owner_id=employee.id,
        resource_label="employee_id",
        action_label="submit",
        redirect_endpoint="employee_loans.list_loans",
    )
    if error_response:
        return error_response
    if loan.status != STATUS_DRAFT:
        flash("Only draft loan requests can be submitted.", "warning")
        return redirect(url_for("employee_loans.view_loan", loan_id=loan_id))

    try:
        config = get_or_create_loan_config()
        approver = require_fixed_approver(config)
        loan.status = STATUS_PENDING_APPROVAL
        loan.approver_user_id = approver.id
        loan.current_assignee_user_id = approver.id
        loan.submitted_at = datetime.utcnow()
        record_action(
            loan=loan,
            action_by_user_id=employee.user_id,
            action_type="submitted",
            from_status=STATUS_DRAFT,
            to_status=STATUS_PENDING_APPROVAL,
        )
        db.session.commit()
        send_loan_submitted_email(loan)
        flash("Loan request submitted for approval.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("employee_loans.view_loan", loan_id=loan_id))
