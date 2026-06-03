from datetime import date
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import ReimbursementRequest
from utils.authz import ROLE_ACCOUNT_ADMIN, get_base_template_for_role, get_current_role, get_current_user, require_roles
from utils.reimbursement_pdf import render_reimbursement_pdf
from utils.reimbursement_service import (
    STATUS_APPROVED_FOR_PAYMENT,
    STATUS_PAID,
    STATUS_PENDING_FINANCE,
    STATUS_REJECTED_FINANCE,
    ensure_transition,
    parse_amount,
    record_action,
    summarize_account_reimbursements,
)
from utils.route_actions import execute_db_action
from utils.workflow_messages import (
    REIMBURSEMENT_APPROVED_BODY,
    REIMBURSEMENT_APPROVED_SUBJECT,
    REIMBURSEMENT_PAID_BODY,
    REIMBURSEMENT_PAID_SUBJECT,
    REIMBURSEMENT_REJECTED_BODY,
    REIMBURSEMENT_REJECTED_SUBJECT,
)
from utils.workflow_email_service import send_reimbursement_status_email


account_reimbursements_bp = Blueprint("account_reimbursements", __name__, url_prefix="/accounts/reimbursements")


@account_reimbursements_bp.before_request
def enforce_account_access():
    return require_roles(ROLE_ACCOUNT_ADMIN)


@account_reimbursements_bp.route("")
def list_reimbursements():
    base_template = get_base_template_for_role(get_current_role())
    reimbursements = (
        ReimbursementRequest.query.filter(
            ReimbursementRequest.status.in_([
                STATUS_PENDING_FINANCE,
                STATUS_APPROVED_FOR_PAYMENT,
                STATUS_PAID,
                STATUS_REJECTED_FINANCE,
            ])
        ).order_by(
            db.case((ReimbursementRequest.status == STATUS_PENDING_FINANCE, 0), else_=1),
            ReimbursementRequest.created_at.desc(),
        )
        .all()
    )
    summary = summarize_account_reimbursements(reimbursements)
    return render_template(
        "accounts/reimbursements.html",
        reimbursements=reimbursements,
        summary=summary,
        base_template=base_template,
    )


@account_reimbursements_bp.route("/<int:request_id>")
def view_reimbursement(request_id):
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)
    return render_template(
        "accounts/reimbursement_detail.html",
        reimbursement=reimbursement,
        base_template=get_base_template_for_role(get_current_role()),
    )


@account_reimbursements_bp.route("/<int:request_id>/approve", methods=["POST"])
def approve_reimbursement(request_id):
    current_user = get_current_user()
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)

    def _mutate():
        ensure_transition(reimbursement, STATUS_APPROVED_FOR_PAYMENT)
        approved_amount_raw = request.form.get("approved_amount")
        fallback_amount = reimbursement.manager_approved_amount or reimbursement.requested_amount
        approved_amount = parse_amount(approved_amount_raw) if approved_amount_raw else Decimal(fallback_amount)
        comments = (request.form.get("comments") or "").strip() or None

        reimbursement.finance_approver_user_id = current_user.id
        reimbursement.finance_approved_amount = approved_amount
        reimbursement.final_amount = approved_amount
        reimbursement.finance_comments = comments
        reimbursement.current_assignee_user_id = current_user.id
        reimbursement.status = STATUS_APPROVED_FOR_PAYMENT

        record_action(
            request_obj=reimbursement,
            action_by_user_id=current_user.id,
            action_type="finance_approved",
            from_status=STATUS_PENDING_FINANCE,
            to_status=STATUS_APPROVED_FOR_PAYMENT,
            comments=comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message="Reimbursement approved for payment.",
        after_commit=lambda: send_reimbursement_status_email(
            reimbursement,
            REIMBURSEMENT_APPROVED_SUBJECT,
            REIMBURSEMENT_APPROVED_BODY,
        ),
    )

    return redirect(url_for("account_reimbursements.view_reimbursement", request_id=request_id))


@account_reimbursements_bp.route("/<int:request_id>/reject", methods=["POST"])
def reject_reimbursement(request_id):
    current_user = get_current_user()
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)
    comments = (request.form.get("comments") or "").strip()
    if not comments:
        flash("Finance comments are required when rejecting a reimbursement.", "danger")
        return redirect(url_for("account_reimbursements.view_reimbursement", request_id=request_id))

    def _mutate():
        ensure_transition(reimbursement, STATUS_REJECTED_FINANCE)
        reimbursement.finance_approver_user_id = current_user.id
        reimbursement.finance_comments = comments
        reimbursement.current_assignee_user_id = current_user.id
        reimbursement.status = STATUS_REJECTED_FINANCE

        record_action(
            request_obj=reimbursement,
            action_by_user_id=current_user.id,
            action_type="finance_rejected",
            from_status=STATUS_PENDING_FINANCE,
            to_status=STATUS_REJECTED_FINANCE,
            comments=comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message="Reimbursement rejected by finance.",
        after_commit=lambda: send_reimbursement_status_email(
            reimbursement,
            REIMBURSEMENT_REJECTED_SUBJECT,
            REIMBURSEMENT_REJECTED_BODY,
        ),
    )

    return redirect(url_for("account_reimbursements.view_reimbursement", request_id=request_id))


@account_reimbursements_bp.route("/<int:request_id>/mark-paid", methods=["POST"])
def mark_paid(request_id):
    current_user = get_current_user()
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)

    payment_date = request.form.get("payment_date")
    if not payment_date:
        flash("Payment date is required.", "danger")
        return redirect(url_for("account_reimbursements.view_reimbursement", request_id=request_id))

    def _mutate():
        ensure_transition(reimbursement, STATUS_PAID)
        reimbursement.finance_approver_user_id = current_user.id
        reimbursement.payment_reference = (request.form.get("payment_reference") or "").strip() or None
        reimbursement.payment_date = date.fromisoformat(payment_date)
        reimbursement.status = STATUS_PAID
        reimbursement.current_assignee_user_id = current_user.id
        reimbursement.final_amount = reimbursement.finance_approved_amount or reimbursement.manager_approved_amount or reimbursement.requested_amount

        record_action(
            request_obj=reimbursement,
            action_by_user_id=current_user.id,
            action_type="marked_paid",
            from_status=STATUS_APPROVED_FOR_PAYMENT,
            to_status=STATUS_PAID,
            comments=reimbursement.payment_reference,
        )
    execute_db_action(
        mutator=_mutate,
        success_message="Reimbursement marked as paid.",
        after_commit=lambda: send_reimbursement_status_email(
            reimbursement,
            REIMBURSEMENT_PAID_SUBJECT,
            REIMBURSEMENT_PAID_BODY,
        ),
    )

    return redirect(url_for("account_reimbursements.view_reimbursement", request_id=request_id))


@account_reimbursements_bp.route("/<int:request_id>/download-pdf")
def download_pdf(request_id):
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)
    return render_reimbursement_pdf(reimbursement, "account_admin")
