from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import ReimbursementRequest
from utils.authz import ROLE_MANAGER, get_current_employee, require_roles
from utils.reimbursement_service import (
    STATUS_PENDING_FINANCE,
    STATUS_PENDING_MANAGER,
    STATUS_REJECTED_MANAGER,
    ensure_transition,
    parse_amount,
    record_action,
)
from utils.route_actions import execute_db_action
from utils.route_guards import require_assigned_resource_or_redirect
from utils.workflow_email_service import (
    send_reimbursement_pending_finance_email,
    send_reimbursement_status_email,
)


manager_reimbursements_bp = Blueprint("manager_reimbursements", __name__, url_prefix="/manager/reimbursements")


@manager_reimbursements_bp.before_request
def enforce_manager_access():
    return require_roles(ROLE_MANAGER)


@manager_reimbursements_bp.route("")
def list_reimbursements():
    manager = get_current_employee()
    status_filter = (request.args.get("status_filter") or "pending").strip().lower()
    allowed_status_filters = {"all", "pending", "approved", "rejected"}
    if status_filter not in allowed_status_filters:
        status_filter = "pending"

    base_query = ReimbursementRequest.query.filter_by(manager_approver_user_id=manager.user_id)
    if status_filter == "pending":
        base_query = base_query.filter(ReimbursementRequest.status == STATUS_PENDING_MANAGER)
    elif status_filter == "approved":
        base_query = base_query.filter(ReimbursementRequest.status == STATUS_PENDING_FINANCE)
    elif status_filter == "rejected":
        base_query = base_query.filter(ReimbursementRequest.status == STATUS_REJECTED_MANAGER)

    reimbursements = (
        base_query
        .order_by(
            db.case((ReimbursementRequest.status == STATUS_PENDING_MANAGER, 0), else_=1),
            ReimbursementRequest.created_at.desc(),
        )
        .all()
    )
    all_reimbursements = ReimbursementRequest.query.filter_by(manager_approver_user_id=manager.user_id).all()
    summary = {
        "pending": sum(1 for item in all_reimbursements if item.status == STATUS_PENDING_MANAGER),
        "approved": sum(1 for item in all_reimbursements if item.status == STATUS_PENDING_FINANCE),
        "rejected": sum(1 for item in all_reimbursements if item.status == STATUS_REJECTED_MANAGER),
        "all": len(all_reimbursements),
    }
    return render_template(
        "manager/reimbursements.html",
        reimbursements=reimbursements,
        summary=summary,
        status_filter=status_filter,
    )


@manager_reimbursements_bp.route("/<int:request_id>")
def view_reimbursement(request_id):
    manager = get_current_employee()
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)
    reimbursement, error_response = require_assigned_resource_or_redirect(
        resource=reimbursement,
        assignee_id=manager.user_id,
        assignee_field="manager_approver_user_id",
        message="This reimbursement is not assigned to you.",
        redirect_endpoint="manager_reimbursements.list_reimbursements",
    )
    if error_response:
        return error_response
    return render_template("manager/reimbursement_detail.html", reimbursement=reimbursement)


@manager_reimbursements_bp.route("/<int:request_id>/approve", methods=["POST"])
def approve_reimbursement(request_id):
    manager = get_current_employee()
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)
    reimbursement, error_response = require_assigned_resource_or_redirect(
        resource=reimbursement,
        assignee_id=manager.user_id,
        assignee_field="manager_approver_user_id",
        message="This reimbursement is not assigned to you.",
        redirect_endpoint="manager_reimbursements.list_reimbursements",
    )
    if error_response:
        return error_response

    def _mutate():
        ensure_transition(reimbursement, STATUS_PENDING_FINANCE)
        approved_amount_raw = request.form.get("approved_amount")
        approved_amount = parse_amount(approved_amount_raw) if approved_amount_raw else Decimal(reimbursement.requested_amount)
        comments = (request.form.get("comments") or "").strip() or None

        reimbursement.manager_approved_amount = approved_amount
        reimbursement.manager_comments = comments
        reimbursement.status = STATUS_PENDING_FINANCE
        reimbursement.current_assignee_user_id = None
        reimbursement.finance_approved_amount = None
        reimbursement.final_amount = None

        record_action(
            request_obj=reimbursement,
            action_by_user_id=manager.user_id,
            action_type="manager_approved",
            from_status=STATUS_PENDING_MANAGER,
            to_status=STATUS_PENDING_FINANCE,
            comments=comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message="Reimbursement forwarded to finance for review.",
        after_commit=lambda: send_reimbursement_pending_finance_email(reimbursement),
    )

    return redirect(url_for("manager_reimbursements.view_reimbursement", request_id=request_id))


@manager_reimbursements_bp.route("/<int:request_id>/reject", methods=["POST"])
def reject_reimbursement(request_id):
    manager = get_current_employee()
    reimbursement = ReimbursementRequest.query.get_or_404(request_id)
    reimbursement, error_response = require_assigned_resource_or_redirect(
        resource=reimbursement,
        assignee_id=manager.user_id,
        assignee_field="manager_approver_user_id",
        message="This reimbursement is not assigned to you.",
        redirect_endpoint="manager_reimbursements.list_reimbursements",
    )
    if error_response:
        return error_response

    comments = (request.form.get("comments") or "").strip()
    if not comments:
        flash("Manager comments are required when rejecting a reimbursement.", "danger")
        return redirect(url_for("manager_reimbursements.view_reimbursement", request_id=request_id))

    def _mutate():
        ensure_transition(reimbursement, STATUS_REJECTED_MANAGER)
        reimbursement.manager_comments = comments
        reimbursement.status = STATUS_REJECTED_MANAGER
        reimbursement.current_assignee_user_id = None

        record_action(
            request_obj=reimbursement,
            action_by_user_id=manager.user_id,
            action_type="manager_rejected",
            from_status=STATUS_PENDING_MANAGER,
            to_status=STATUS_REJECTED_MANAGER,
            comments=comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message="Reimbursement rejected.",
        after_commit=lambda: send_reimbursement_status_email(
            reimbursement,
            "Reimbursement Rejected By Manager",
            "Your reimbursement request was rejected during manager review.",
        ),
    )

    return redirect(url_for("manager_reimbursements.view_reimbursement", request_id=request_id))
