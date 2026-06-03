from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import AccountsRequest, AccountsRequestConfig, AccountsRequestType, User
from utils.accounts_request_service import (
    STATUS_APPROVED,
    STATUS_CLOSED,
    STATUS_EXPENSE_RECORDED,
    STATUS_PENDING_APPROVAL,
    STATUS_REJECTED,
    ensure_transition,
    parse_amount,
    record_action,
    seed_accounts_request_types,
)
from utils.accounts_request_pdf import render_accounts_request_pdf
from utils.authz import ROLE_ADMIN, get_current_user, get_role_by_name, require_roles
from utils.route_actions import execute_db_action
from utils.workflow_messages import (
    ACCOUNTS_REQUEST_APPROVED_BODY,
    ACCOUNTS_REQUEST_APPROVED_SUBJECT,
    ACCOUNTS_REQUEST_APPROVED_SUCCESS,
    ACCOUNTS_REQUEST_CLOSED_BODY,
    ACCOUNTS_REQUEST_CLOSED_SUBJECT,
    ACCOUNTS_REQUEST_CLOSED_SUCCESS,
    ACCOUNTS_REQUEST_REJECTED_BODY,
    ACCOUNTS_REQUEST_REJECTED_SUBJECT,
    ACCOUNTS_REQUEST_REJECTED_SUCCESS,
)
from utils.workflow_email_service import send_accounts_request_status_email


admin_account_requests_bp = Blueprint("admin_account_requests", __name__, url_prefix="/admin/accounts")


@admin_account_requests_bp.before_request
def enforce_admin_access():
    return require_roles(ROLE_ADMIN)


@admin_account_requests_bp.route("/requests")
def list_requests():
    status_filter = (request.args.get("status_filter") or "pending").strip().lower()
    allowed_status_filters = {"all", "pending", "approved", "rejected"}
    if status_filter not in allowed_status_filters:
        status_filter = "pending"

    base_query = AccountsRequest.query
    if status_filter == "pending":
        base_query = base_query.filter(AccountsRequest.status == STATUS_PENDING_APPROVAL)
    elif status_filter == "approved":
        base_query = base_query.filter(AccountsRequest.status.in_([STATUS_APPROVED, STATUS_EXPENSE_RECORDED, STATUS_CLOSED]))
    elif status_filter == "rejected":
        base_query = base_query.filter(AccountsRequest.status == STATUS_REJECTED)

    requests_list = base_query.order_by(
        db.case((AccountsRequest.status == STATUS_PENDING_APPROVAL, 0), else_=1),
        AccountsRequest.created_at.desc(),
    ).all()
    all_requests = AccountsRequest.query.all()
    summary = {
        "pending": sum(1 for item in all_requests if item.status == STATUS_PENDING_APPROVAL),
        "approved": sum(1 for item in all_requests if item.status in [STATUS_APPROVED, STATUS_EXPENSE_RECORDED, STATUS_CLOSED]),
        "rejected": sum(1 for item in all_requests if item.status == STATUS_REJECTED),
        "all": len(all_requests),
    }
    return render_template(
        "admin/accounts_requests.html",
        requests_list=requests_list,
        summary=summary,
        status_filter=status_filter,
    )


@admin_account_requests_bp.route("/requests/<int:request_id>")
def view_request(request_id):
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    return render_template("admin/accounts_request_detail.html", accounts_request=accounts_request)


@admin_account_requests_bp.route("/requests/<int:request_id>/download-summary")
def download_summary(request_id):
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    return render_accounts_request_pdf(accounts_request, "admin")


@admin_account_requests_bp.route("/requests/<int:request_id>/approve", methods=["POST"])
def approve_request(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    def _mutate():
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
    execute_db_action(
        mutator=_mutate,
        success_message=ACCOUNTS_REQUEST_APPROVED_SUCCESS,
        after_commit=lambda: send_accounts_request_status_email(
            accounts_request,
            ACCOUNTS_REQUEST_APPROVED_SUBJECT,
            ACCOUNTS_REQUEST_APPROVED_BODY,
        ),
    )
    return redirect(url_for("admin_account_requests.view_request", request_id=request_id))


@admin_account_requests_bp.route("/requests/<int:request_id>/reject", methods=["POST"])
def reject_request(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    rejection_comments = (request.form.get("approval_comments") or "").strip()
    if not rejection_comments:
        flash("Comments are required when rejecting a request.", "danger")
        return redirect(url_for("admin_account_requests.view_request", request_id=request_id))
    def _mutate():
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
    execute_db_action(
        mutator=_mutate,
        success_message=ACCOUNTS_REQUEST_REJECTED_SUCCESS,
        after_commit=lambda: send_accounts_request_status_email(
            accounts_request,
            ACCOUNTS_REQUEST_REJECTED_SUBJECT,
            ACCOUNTS_REQUEST_REJECTED_BODY,
        ),
    )
    return redirect(url_for("admin_account_requests.view_request", request_id=request_id))


@admin_account_requests_bp.route("/requests/<int:request_id>/close", methods=["POST"])
def close_request(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    closure_comments = (request.form.get("closure_comments") or "").strip() or None
    def _mutate():
        ensure_transition(accounts_request, STATUS_CLOSED)
        accounts_request.status = STATUS_CLOSED
        accounts_request.closure_comments = closure_comments
        accounts_request.closed_at = datetime.utcnow()
        record_action(
            request_obj=accounts_request,
            action_by_user_id=current_user.id,
            from_status=STATUS_EXPENSE_RECORDED,
            to_status=STATUS_CLOSED,
            action_type="closed",
            comments=closure_comments,
        )
    execute_db_action(
        mutator=_mutate,
        success_message=ACCOUNTS_REQUEST_CLOSED_SUCCESS,
        after_commit=lambda: send_accounts_request_status_email(
            accounts_request,
            ACCOUNTS_REQUEST_CLOSED_SUBJECT,
            ACCOUNTS_REQUEST_CLOSED_BODY,
        ),
    )
    return redirect(url_for("admin_account_requests.view_request", request_id=request_id))


@admin_account_requests_bp.route("/settings", methods=["GET", "POST"])
def settings():
    seed_accounts_request_types()
    config = AccountsRequestConfig.query.order_by(AccountsRequestConfig.id.asc()).first()
    approvers = (
        User.query
        .filter_by(is_active=True)
        .order_by(User.display_name.asc(), User.email.asc())
        .all()
    )
    if request.method == "POST":
        approver_user_id = request.form.get("default_approver_user_id")
        if not approver_user_id:
            flash("Default approver is required.", "danger")
            return redirect(url_for("admin_account_requests.settings"))

        if not config:
            config = AccountsRequestConfig(default_approver_user_id=int(approver_user_id))
            db.session.add(config)
        else:
            config.default_approver_user_id = int(approver_user_id)
        config.allow_partial_approval = request.form.get("allow_partial_approval") == "true"
        db.session.commit()
        flash("Accounts settings updated successfully.", "success")
        return redirect(url_for("admin_account_requests.settings"))

    return render_template("admin/accounts_settings.html", config=config, approvers=approvers)


@admin_account_requests_bp.route("/request-types", methods=["GET", "POST"])
def request_types():
    seed_accounts_request_types()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip() or None
        if not name:
            flash("Type name is required.", "danger")
            return redirect(url_for("admin_account_requests.request_types"))
        if AccountsRequestType.query.filter(db.func.lower(AccountsRequestType.name) == name.lower()).first():
            flash("That request type already exists.", "warning")
            return redirect(url_for("admin_account_requests.request_types"))
        db.session.add(AccountsRequestType(name=name, description=description, is_active=True))
        db.session.commit()
        flash("Accounts request type added.", "success")
        return redirect(url_for("admin_account_requests.request_types"))

    request_types_list = AccountsRequestType.query.order_by(
        AccountsRequestType.is_active.desc(),
        AccountsRequestType.name.asc(),
    ).all()
    return render_template("admin/accounts_request_types.html", request_types=request_types_list)


@admin_account_requests_bp.route("/request-types/<int:type_id>/toggle", methods=["POST"])
def toggle_request_type(type_id):
    request_type = AccountsRequestType.query.get_or_404(type_id)
    request_type.is_active = not request_type.is_active
    db.session.commit()
    flash("Accounts request type updated.", "success")
    return redirect(url_for("admin_account_requests.request_types"))
