from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import ReimbursementRequest, ReimbursementType, User
from utils.authz import ROLE_ACCOUNT_ADMIN, ROLE_ADMIN, get_role_by_name, require_roles
from utils.reimbursement_service import (
    get_or_create_reimbursement_config,
    seed_reimbursement_types,
    STATUS_APPROVED_FOR_PAYMENT,
    STATUS_PAID,
    STATUS_PENDING_FINANCE,
    STATUS_PENDING_MANAGER,
    STATUS_REJECTED_FINANCE,
    STATUS_REJECTED_MANAGER,
)


admin_reimbursements_bp = Blueprint("admin_reimbursements", __name__, url_prefix="/admin/reimbursements")


@admin_reimbursements_bp.before_request
def enforce_admin_access():
    return require_roles(ROLE_ADMIN)


@admin_reimbursements_bp.route("/settings", methods=["GET", "POST"])
def settings():
    seed_reimbursement_types()
    config = get_or_create_reimbursement_config()
    account_admin_role = get_role_by_name(ROLE_ACCOUNT_ADMIN)
    finance_users = (
        User.query.filter_by(role_id=account_admin_role.id).order_by(User.display_name.asc(), User.email.asc()).all()
        if account_admin_role
        else []
    )
    approver_users = User.query.order_by(User.display_name.asc(), User.email.asc()).all()

    if request.method == "POST":
        config.approver_mode = request.form.get("approver_mode", "reporting_manager")
        fixed_user_id = request.form.get("fixed_approver_user_id")
        config.fixed_approver_user_id = int(fixed_user_id) if fixed_user_id else None
        config.allow_partial_approval = request.form.get("allow_partial_approval") == "true"
        config.allow_multiple_attachments = request.form.get("allow_multiple_attachments") == "true"
        db.session.commit()
        flash("Reimbursement settings updated successfully.", "success")
        return redirect(url_for("admin_reimbursements.settings"))

    return render_template(
        "admin/reimbursement_settings.html",
        config=config,
        finance_users=finance_users,
        approver_users=approver_users,
    )


@admin_reimbursements_bp.route("/types", methods=["GET", "POST"])
def types():
    seed_reimbursement_types()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = (request.form.get("description") or "").strip()
        if not name:
            flash("Type name is required.", "danger")
            return redirect(url_for("admin_reimbursements.types"))

        if ReimbursementType.query.filter(db.func.lower(ReimbursementType.name) == name.lower()).first():
            flash("That reimbursement type already exists.", "warning")
            return redirect(url_for("admin_reimbursements.types"))

        db.session.add(ReimbursementType(name=name, description=description or None, is_active=True))
        db.session.commit()
        flash("Reimbursement type added.", "success")
        return redirect(url_for("admin_reimbursements.types"))

    types_list = ReimbursementType.query.order_by(ReimbursementType.is_active.desc(), ReimbursementType.name.asc()).all()
    return render_template("admin/reimbursement_types.html", reimbursement_types=types_list)


@admin_reimbursements_bp.route("/types/<int:type_id>/toggle", methods=["POST"])
def toggle_type(type_id):
    reimbursement_type = ReimbursementType.query.get_or_404(type_id)
    reimbursement_type.is_active = not reimbursement_type.is_active
    db.session.commit()
    flash("Reimbursement type updated.", "success")
    return redirect(url_for("admin_reimbursements.types"))


@admin_reimbursements_bp.route("/reports")
def reports():
    status_filter = (request.args.get("status_filter") or "pending").strip().lower()
    allowed_status_filters = {"all", "pending", "approved", "rejected"}
    if status_filter not in allowed_status_filters:
        status_filter = "pending"

    base_query = ReimbursementRequest.query
    if status_filter == "pending":
        base_query = base_query.filter(
            ReimbursementRequest.status.in_([STATUS_PENDING_MANAGER, STATUS_PENDING_FINANCE])
        )
    elif status_filter == "approved":
        base_query = base_query.filter(ReimbursementRequest.status.in_([STATUS_APPROVED_FOR_PAYMENT, STATUS_PAID]))
    elif status_filter == "rejected":
        base_query = base_query.filter(ReimbursementRequest.status.in_([STATUS_REJECTED_MANAGER, STATUS_REJECTED_FINANCE]))

    reimbursements = base_query.order_by(ReimbursementRequest.created_at.desc()).all()
    all_reimbursements = ReimbursementRequest.query.all()
    summary = {
        "pending": sum(1 for item in all_reimbursements if item.status in {STATUS_PENDING_MANAGER, STATUS_PENDING_FINANCE}),
        "approved": sum(1 for item in all_reimbursements if item.status in {STATUS_APPROVED_FOR_PAYMENT, STATUS_PAID}),
        "rejected": sum(1 for item in all_reimbursements if item.status in {STATUS_REJECTED_MANAGER, STATUS_REJECTED_FINANCE}),
        "all": len(all_reimbursements),
    }
    return render_template(
        "admin/reimbursement_reports.html",
        reimbursements=reimbursements,
        summary=summary,
        status_filter=status_filter,
    )
