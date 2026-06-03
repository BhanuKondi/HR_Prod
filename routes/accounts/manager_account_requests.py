from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import AccountsRequest
from utils.accounts_request_service import (
    STATUS_APPROVED,
    STATUS_CLOSED,
    STATUS_EXPENSE_RECORDED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    ensure_transition,
    parse_amount,
    record_action,
)
from utils.accounts_request_pdf import render_accounts_request_pdf
from utils.authz import ROLE_MANAGER, get_current_user, require_roles
from utils.authz import ROLE_ACCOUNT_ADMIN, get_base_template_for_role, get_current_role
from utils.route_guards import require_assigned_resource_or_redirect
from utils.workflow_email_service import send_accounts_request_status_email


manager_account_requests_bp = Blueprint(
    "manager_account_requests",
    __name__,
    url_prefix="/manager/accounts",
)


@manager_account_requests_bp.before_request
def enforce_manager_access():
    return require_roles(ROLE_MANAGER, ROLE_ACCOUNT_ADMIN)


@manager_account_requests_bp.route("/requests")
def list_requests():
    current_user = get_current_user()
    base_template = get_base_template_for_role(get_current_role())
    status_filter = (request.args.get("status_filter") or "pending").strip().lower()
    allowed_status_filters = {"all", "pending", "approved", "rejected"}
    if status_filter not in allowed_status_filters:
        status_filter = "pending"

    base_query = AccountsRequest.query.filter_by(approver_user_id=current_user.id)
    if status_filter == "pending":
        base_query = base_query.filter(AccountsRequest.status == STATUS_PENDING_APPROVAL)
    elif status_filter == "approved":
        base_query = base_query.filter(AccountsRequest.status.in_([STATUS_APPROVED, STATUS_EXPENSE_RECORDED, STATUS_CLOSED]))
    elif status_filter == "rejected":
        base_query = base_query.filter(AccountsRequest.status == STATUS_REJECTED)

    requests_list = (
        base_query
        .order_by(
            db.case((AccountsRequest.status == STATUS_PENDING_APPROVAL, 0), else_=1),
            AccountsRequest.created_at.desc(),
        )
        .all()
    )
    all_requests = AccountsRequest.query.filter_by(approver_user_id=current_user.id).all()
    summary = {
        "pending": sum(1 for item in all_requests if item.status == STATUS_PENDING_APPROVAL),
        "approved": sum(1 for item in all_requests if item.status in [STATUS_APPROVED, STATUS_EXPENSE_RECORDED, STATUS_CLOSED]),
        "rejected": sum(1 for item in all_requests if item.status == STATUS_REJECTED),
        "all": len(all_requests),
    }
    return render_template(
        "manager/accounts_requests.html",
        requests_list=requests_list,
        summary=summary,
        base_template=base_template,
        status_filter=status_filter,
    )


@manager_account_requests_bp.route("/requests/<int:request_id>")
def view_request(request_id):
    current_user = get_current_user()
    base_template = get_base_template_for_role(get_current_role())
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    accounts_request, error_response = require_assigned_resource_or_redirect(
        resource=accounts_request,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This request is not assigned to you.",
        redirect_endpoint="manager_account_requests.list_requests",
    )
    if error_response:
        return error_response
    return render_template(
        "manager/accounts_request_detail.html",
        accounts_request=accounts_request,
        base_template=base_template,
    )


@manager_account_requests_bp.route("/requests/<int:request_id>/download-summary")
def download_summary(request_id):
    current_user = get_current_user()
    current_role = get_current_role()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    accounts_request, error_response = require_assigned_resource_or_redirect(
        resource=accounts_request,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This request is not assigned to you.",
        redirect_endpoint="manager_account_requests.list_requests",
    )
    if error_response:
        return error_response
    return render_accounts_request_pdf(accounts_request, current_role or "manager")


@manager_account_requests_bp.route("/requests/<int:request_id>/approve", methods=["POST"])
def approve_request(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    accounts_request, error_response = require_assigned_resource_or_redirect(
        resource=accounts_request,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This request is not assigned to you.",
        redirect_endpoint="manager_account_requests.list_requests",
    )
    if error_response:
        return error_response

    try:
        ensure_transition(accounts_request, STATUS_APPROVED)
        approved_amount = parse_amount(request.form.get("approved_amount"))
        approval_comments = (request.form.get("approval_comments") or "").strip() or None
        accounts_request.approved_amount = approved_amount
        accounts_request.approval_comments = approval_comments
        accounts_request.status = STATUS_APPROVED
        accounts_request.approved_at = datetime.utcnow()
        record_action(
            request_obj=accounts_request,
            action_by_user_id=current_user.id,
            from_status=STATUS_PENDING_APPROVAL,
            to_status=STATUS_APPROVED,
            action_type="approved",
            comments=approval_comments,
        )
        db.session.commit()
        send_accounts_request_status_email(
            accounts_request,
            "Accounts Request Approved",
            "Your accounts request has been approved and is ready for expense execution.",
        )
        flash("Accounts request approved.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("manager_account_requests.view_request", request_id=request_id))


@manager_account_requests_bp.route("/requests/<int:request_id>/reject", methods=["POST"])
def reject_request(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    accounts_request, error_response = require_assigned_resource_or_redirect(
        resource=accounts_request,
        assignee_id=current_user.id,
        assignee_field="approver_user_id",
        message="This request is not assigned to you.",
        redirect_endpoint="manager_account_requests.list_requests",
    )
    if error_response:
        return error_response

    rejection_comments = (request.form.get("approval_comments") or "").strip()
    if not rejection_comments:
        flash("Comments are required when rejecting a request.", "danger")
        return redirect(url_for("manager_account_requests.view_request", request_id=request_id))

    try:
        ensure_transition(accounts_request, STATUS_REJECTED)
        accounts_request.approval_comments = rejection_comments
        accounts_request.status = STATUS_REJECTED
        record_action(
            request_obj=accounts_request,
            action_by_user_id=current_user.id,
            from_status=STATUS_PENDING_APPROVAL,
            to_status=STATUS_REJECTED,
            action_type="rejected",
            comments=rejection_comments,
        )
        db.session.commit()
        send_accounts_request_status_email(
            accounts_request,
            "Accounts Request Rejected",
            "Your accounts request was rejected during approval review.",
        )
        flash("Accounts request rejected.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("manager_account_requests.view_request", request_id=request_id))
