from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import EmployeeLoan
from utils.authz import ROLE_MANAGER, get_current_user, require_roles
from utils.loan_service import (
    STATUS_PENDING_APPROVAL,
    STATUS_PENDING_PAYMENT,
    STATUS_REJECTED,
    calculate_monthly_installment,
    ensure_transition,
    parse_amount,
    record_action,
)
from utils.route_guards import require_assigned_resource_or_redirect
from utils.route_actions import execute_db_action
from utils.workflow_messages import (
    LOAN_APPROVED_SUCCESS,
    LOAN_REJECTED_BODY,
    LOAN_REJECTED_SUBJECT,
    LOAN_REJECTED_SUCCESS,
)
from utils.workflow_email_service import send_loan_pending_payment_email, send_loan_status_email


manager_loans_bp = Blueprint("manager_loans", __name__, url_prefix="/manager/loans")


@manager_loans_bp.before_request
def enforce_access():
    return require_roles(ROLE_MANAGER)


@manager_loans_bp.route("")
def list_loans():
    current_user = get_current_user()
    status_filter = (request.args.get("status_filter") or "pending").strip().lower()
    allowed_status_filters = {"all", "pending", "approved", "rejected"}
    if status_filter not in allowed_status_filters:
        status_filter = "pending"

    base_query = EmployeeLoan.query.filter_by(approver_user_id=current_user.id)
    if status_filter == "pending":
        base_query = base_query.filter(EmployeeLoan.status == STATUS_PENDING_APPROVAL)
    elif status_filter == "approved":
        base_query = base_query.filter(EmployeeLoan.status == STATUS_PENDING_PAYMENT)
    elif status_filter == "rejected":
        base_query = base_query.filter(EmployeeLoan.status == STATUS_REJECTED)

    loans = (
        base_query
        .order_by(
            db.case((EmployeeLoan.status == STATUS_PENDING_APPROVAL, 0), else_=1),
            EmployeeLoan.created_at.desc(),
        )
        .all()
    )
    all_loans = EmployeeLoan.query.filter_by(approver_user_id=current_user.id).all()
    summary = {
        "pending": sum(1 for loan in all_loans if loan.status == STATUS_PENDING_APPROVAL),
        "approved": sum(1 for loan in all_loans if loan.status == STATUS_PENDING_PAYMENT),
        "rejected": sum(1 for loan in all_loans if loan.status == STATUS_REJECTED),
        "all": len(all_loans),
    }
    return render_template("manager/loans.html", loans=loans, summary=summary, status_filter=status_filter)


@manager_loans_bp.route("/<int:loan_id>")
def view_loan(loan_id):
    current_user = get_current_user()
    loan = EmployeeLoan.query.get_or_404(loan_id)
    loan, error_response = require_assigned_resource_or_redirect(
        resource=loan,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This loan request is not assigned to you.",
        redirect_endpoint="manager_loans.list_loans",
    )
    if error_response:
        return error_response
    return render_template("manager/loan_detail.html", loan=loan)


@manager_loans_bp.route("/<int:loan_id>/approve", methods=["POST"])
def approve_loan(loan_id):
    current_user = get_current_user()
    loan = EmployeeLoan.query.get_or_404(loan_id)
    loan, error_response = require_assigned_resource_or_redirect(
        resource=loan,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This loan request is not assigned to you.",
        redirect_endpoint="manager_loans.list_loans",
    )
    if error_response:
        return error_response

    def _mutate():
        ensure_transition(loan, STATUS_PENDING_PAYMENT)
        approved_amount = parse_amount(request.form.get("approved_amount"))
        comments = (request.form.get("comments") or "").strip() or None
        loan.approved_amount = approved_amount
        loan.monthly_installment = calculate_monthly_installment(approved_amount, int(loan.total_installments or 1))
        loan.approval_comments = comments
        loan.status = STATUS_PENDING_PAYMENT
        loan.approved_at = datetime.utcnow()
        loan.current_assignee_user_id = None
        record_action(
            loan=loan,
            action_by_user_id=current_user.id,
            action_type="approved",
            from_status=STATUS_PENDING_APPROVAL,
            to_status=STATUS_PENDING_PAYMENT,
            comments=comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message=LOAN_APPROVED_SUCCESS,
        after_commit=lambda: send_loan_pending_payment_email(loan),
    )
    return redirect(url_for("manager_loans.view_loan", loan_id=loan_id))


@manager_loans_bp.route("/<int:loan_id>/reject", methods=["POST"])
def reject_loan(loan_id):
    current_user = get_current_user()
    loan = EmployeeLoan.query.get_or_404(loan_id)
    loan, error_response = require_assigned_resource_or_redirect(
        resource=loan,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This loan request is not assigned to you.",
        redirect_endpoint="manager_loans.list_loans",
    )
    if error_response:
        return error_response
    comments = (request.form.get("comments") or "").strip()
    if not comments:
        flash("Comments are required when rejecting a loan request.", "danger")
        return redirect(url_for("manager_loans.view_loan", loan_id=loan_id))

    def _mutate():
        ensure_transition(loan, STATUS_REJECTED)
        loan.approval_comments = comments
        loan.status = STATUS_REJECTED
        loan.current_assignee_user_id = None
        record_action(
            loan=loan,
            action_by_user_id=current_user.id,
            action_type="rejected",
            from_status=STATUS_PENDING_APPROVAL,
            to_status=STATUS_REJECTED,
            comments=comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message=LOAN_REJECTED_SUCCESS,
        after_commit=lambda: send_loan_status_email(
            loan,
            LOAN_REJECTED_SUBJECT,
            LOAN_REJECTED_BODY,
        ),
    )
    return redirect(url_for("manager_loans.view_loan", loan_id=loan_id))
