from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import EmployeeLoan
from utils.authz import ROLE_ACCOUNT_ADMIN, get_base_template_for_role, get_current_role, get_current_user, require_roles
from utils.loan_service import (
    STATUS_PAID,
    STATUS_PENDING_PAYMENT,
    ensure_transition,
    parse_repayment_month,
    record_action,
    summarize_account_loans,
)
from utils.route_actions import execute_db_action
from utils.workflow_messages import LOAN_PAID_BODY, LOAN_PAID_SUBJECT, LOAN_PAID_SUCCESS
from utils.workflow_email_service import send_loan_status_email


account_loans_bp = Blueprint("account_loans", __name__, url_prefix="/accounts/loans")


@account_loans_bp.before_request
def enforce_access():
    return require_roles(ROLE_ACCOUNT_ADMIN)


@account_loans_bp.route("")
def list_loans():
    loans = (
        EmployeeLoan.query.filter(EmployeeLoan.status.in_([STATUS_PENDING_PAYMENT, STATUS_PAID]))
        .order_by(
            db.case((EmployeeLoan.status == STATUS_PENDING_PAYMENT, 0), else_=1),
            EmployeeLoan.created_at.desc(),
        )
        .all()
    )
    summary = summarize_account_loans(loans)
    return render_template(
        "accounts/loans.html",
        loans=loans,
        summary=summary,
        base_template=get_base_template_for_role(get_current_role()),
    )


@account_loans_bp.route("/<int:loan_id>")
def view_loan(loan_id):
    loan = EmployeeLoan.query.get_or_404(loan_id)
    return render_template(
        "accounts/loan_detail.html",
        loan=loan,
        base_template=get_base_template_for_role(get_current_role()),
    )


@account_loans_bp.route("/<int:loan_id>/mark-paid", methods=["POST"])
def mark_paid(loan_id):
    current_user = get_current_user()
    loan = EmployeeLoan.query.get_or_404(loan_id)
    payment_date = request.form.get("payment_date")
    if not payment_date:
        flash("Payment date is required.", "danger")
        return redirect(url_for("account_loans.view_loan", loan_id=loan_id))

    def _mutate():
        ensure_transition(loan, STATUS_PAID)
        repayment_start_month, repayment_start_year = parse_repayment_month(request.form.get("repayment_start"))
        loan.account_admin_user_id = current_user.id
        loan.finance_comments = (request.form.get("finance_comments") or "").strip() or None
        loan.payment_reference = (request.form.get("payment_reference") or "").strip() or None
        loan.payment_date = datetime.strptime(payment_date, "%Y-%m-%d").date()
        loan.repayment_start_month = repayment_start_month
        loan.repayment_start_year = repayment_start_year
        loan.status = STATUS_PAID
        loan.paid_at = datetime.utcnow()
        loan.current_assignee_user_id = current_user.id
        record_action(
            loan=loan,
            action_by_user_id=current_user.id,
            action_type="marked_paid",
            from_status=STATUS_PENDING_PAYMENT,
            to_status=STATUS_PAID,
            comments=loan.payment_reference or loan.finance_comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message=LOAN_PAID_SUCCESS,
        after_commit=lambda: send_loan_status_email(
            loan,
            LOAN_PAID_SUBJECT,
            LOAN_PAID_BODY,
        ),
    )
    return redirect(url_for("account_loans.view_loan", loan_id=loan_id))
