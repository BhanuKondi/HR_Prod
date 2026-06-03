from datetime import date, datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from models.db import db
from models.models import AccountsRequest, AccountsRequestType, Company
from utils.accounts_request_service import (
    ALLOWED_ATTACHMENT_ACCEPT,
    ALLOWED_ATTACHMENT_LABEL,
    PAYMENT_MODE_CASH,
    PAYMENT_MODE_DIRECT,
    PAYMENT_MODE_PAY_LANDLORD,
    PAYMENT_MODE_REIMBURSE_DIRECTOR,
    DIRECTOR_HOUSE_RENT_TYPE_NAME,
    STAGE_POST_EXPENSE,
    STAGE_PRE_APPROVAL,
    STATUS_APPROVED,
    STATUS_CLOSED,
    STATUS_DRAFT,
    STATUS_EXPENSE_RECORDED,
    STATUS_PENDING_APPROVAL,
    add_attachments,
    ensure_transition,
    generate_request_no,
    get_accounts_request_config,
    parse_amount,
    record_action,
    require_configured_approver,
    seed_accounts_request_types,
)
from utils.accounts_request_pdf import render_accounts_request_pdf
from utils.authz import (
    ROLE_ACCOUNT_ADMIN,
    ROLE_ADMIN,
    get_base_template_for_role,
    get_current_role,
    get_current_user,
    normalize_role_name,
    require_roles,
)
from utils.company_service import get_active_companies
from utils.workflow_email_service import (
    send_accounts_request_ready_for_closure_email,
    send_accounts_request_status_email,
    send_accounts_request_submitted_email,
)


account_requests_bp = Blueprint("account_requests", __name__, url_prefix="/accounts/requests")


@account_requests_bp.before_request
def enforce_account_admin_access():
    return require_roles(ROLE_ACCOUNT_ADMIN, ROLE_ADMIN)


@account_requests_bp.route("")
def list_requests():
    current_user = get_current_user()
    base_template = get_base_template_for_role(get_current_role())
    requests_list = (
        AccountsRequest.query.filter_by(created_by_user_id=current_user.id)
        .order_by(AccountsRequest.created_at.desc(), AccountsRequest.id.desc())
        .all()
    )
    summary = {
        "draft": sum(1 for item in requests_list if item.status == STATUS_DRAFT),
        "pending_approval": sum(1 for item in requests_list if item.status == STATUS_PENDING_APPROVAL),
        "approved": sum(1 for item in requests_list if item.status == STATUS_APPROVED),
        "awaiting_closure": sum(1 for item in requests_list if item.status == STATUS_EXPENSE_RECORDED),
        "closed": sum(1 for item in requests_list if item.status == STATUS_CLOSED),
    }
    return render_template(
        "accounts/requests.html",
        requests_list=requests_list,
        summary=summary,
        base_template=base_template,
    )


@account_requests_bp.route("/new")
def new_request():
    seed_accounts_request_types()
    base_template = get_base_template_for_role(get_current_role())
    types = AccountsRequestType.query.filter_by(is_active=True).order_by(AccountsRequestType.name.asc()).all()
    director_type_name = DIRECTOR_HOUSE_RENT_TYPE_NAME.lower()
    return render_template(
        "accounts/request_form.html",
        base_template=base_template,
        request_types=types,
        director_type_name=director_type_name,
        companies=get_active_companies(),
        allowed_attachment_accept=ALLOWED_ATTACHMENT_ACCEPT,
        allowed_attachment_label=ALLOWED_ATTACHMENT_LABEL,
        payment_modes=[
            (PAYMENT_MODE_CASH, "Cash Withdrawal"),
            (PAYMENT_MODE_DIRECT, "Direct Payment"),
            (PAYMENT_MODE_PAY_LANDLORD, "Pay Landlord"),
            (PAYMENT_MODE_REIMBURSE_DIRECTOR, "Reimburse Director"),
        ],
    )


@account_requests_bp.route("/create", methods=["POST"])
def create_request():
    current_user = get_current_user()

    try:
        config = get_accounts_request_config()
        approver = require_configured_approver(config)
        request_type_id = int(request.form.get("request_type_id"))
        request_type = AccountsRequestType.query.filter_by(id=request_type_id, is_active=True).first()
        if not request_type:
            raise ValueError("Please select a valid request type.")

        is_director_rent = request_type.name.strip().lower() == DIRECTOR_HOUSE_RENT_TYPE_NAME.lower()
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        requested_amount = parse_amount(request.form.get("requested_amount"))
        company_id = int(request.form.get("company_id"))
        payment_mode = request.form.get("payment_mode")
        vendor_name = (request.form.get("vendor_name") or "").strip() or None
        action = request.form.get("form_action", "draft")
        company = Company.query.filter_by(id=company_id, is_active=True).first()
        rent_month = (request.form.get("rent_month") or "").strip()
        property_address = (request.form.get("property_address") or "").strip()
        landlord_name = (request.form.get("landlord_name") or "").strip()
        landlord_pan = (request.form.get("landlord_pan") or "").strip()
        lease_reference = (request.form.get("lease_reference") or "").strip()
        notes = (request.form.get("notes") or "").strip()
        valid_payment_modes = {
            PAYMENT_MODE_CASH,
            PAYMENT_MODE_DIRECT,
            PAYMENT_MODE_PAY_LANDLORD,
            PAYMENT_MODE_REIMBURSE_DIRECTOR,
        }

        if not company:
            raise ValueError("Please select a valid company.")
        if payment_mode not in valid_payment_modes:
            raise ValueError("Payment mode is invalid.")

        if is_director_rent:
            if normalize_role_name(approver.role.name if approver and approver.role else None) != ROLE_ACCOUNT_ADMIN:
                raise ValueError(
                    "Director house rent requests must be routed to an Account Admin approver. "
                    "Please update Accounts Settings."
                )
            if payment_mode not in {PAYMENT_MODE_PAY_LANDLORD, PAYMENT_MODE_REIMBURSE_DIRECTOR}:
                raise ValueError("For director house rent, choose either Pay Landlord or Reimburse Director.")
            if not rent_month:
                raise ValueError("Rent month is required for director house rent requests.")
            if not property_address:
                raise ValueError("Property address is required for director house rent requests.")
            if not landlord_name:
                raise ValueError("Landlord name is required for director house rent requests.")

            if not title:
                title = f"Director House Rent - {rent_month}"
            structured_sections = [
                f"Rent Month: {rent_month}",
                f"Property Address: {property_address}",
                f"Landlord Name: {landlord_name}",
                f"Landlord PAN: {landlord_pan or '-'}",
                f"Lease/Agreement Reference: {lease_reference or '-'}",
                f"Payment Mode: {payment_mode.replace('_', ' ').title()}",
            ]
            if notes:
                structured_sections.append(f"Additional Notes: {notes}")
            free_text = description or "Director owner housing rent expense."
            description = f"{free_text}\n\n" + "\n".join(structured_sections)
            if not vendor_name:
                vendor_name = landlord_name if payment_mode == PAYMENT_MODE_PAY_LANDLORD else (current_user.display_name or current_user.email)
        else:
            if not title:
                raise ValueError("Title is required.")
            if not description:
                raise ValueError("Description is required.")

        status = STATUS_DRAFT
        submitted_at = None
        if action == "submit":
            status = STATUS_PENDING_APPROVAL
            submitted_at = datetime.utcnow()

        accounts_request = AccountsRequest(
            request_no=generate_request_no(),
            request_type_id=request_type_id,
            company_id=company.id,
            created_by_user_id=current_user.id,
            approver_user_id=approver.id,
            title=title,
            description=description,
            requested_amount=requested_amount,
            payment_mode=payment_mode,
            vendor_name=vendor_name,
            status=status,
            submitted_at=submitted_at,
        )
        db.session.add(accounts_request)
        db.session.flush()

        attachment_count = add_attachments(accounts_request, request.files.getlist("estimate_attachments"), STAGE_PRE_APPROVAL)
        if is_director_rent and attachment_count == 0:
            raise ValueError("Please upload at least one lease or rent-proof attachment for director house rent requests.")
        record_action(
            request_obj=accounts_request,
            action_by_user_id=current_user.id,
            action_type="submitted" if status == STATUS_PENDING_APPROVAL else "created",
            from_status=None,
            to_status=status,
        )
        db.session.commit()
        if status == STATUS_PENDING_APPROVAL:
            send_accounts_request_submitted_email(accounts_request)
        flash(
            "Accounts request submitted for approval." if status == STATUS_PENDING_APPROVAL else "Accounts request draft saved.",
            "success",
        )
        return redirect(url_for("account_requests.view_request", request_id=accounts_request.id))
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("account_requests.new_request"))


@account_requests_bp.route("/<int:request_id>")
def view_request(request_id):
    current_user = get_current_user()
    base_template = get_base_template_for_role(get_current_role())
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    if accounts_request.created_by_user_id != current_user.id:
        flash("You can view only your own accounts requests.", "danger")
        return redirect(url_for("account_requests.list_requests"))
    return render_template(
        "accounts/request_detail.html",
        accounts_request=accounts_request,
        base_template=base_template,
        allowed_attachment_accept=ALLOWED_ATTACHMENT_ACCEPT,
        allowed_attachment_label=ALLOWED_ATTACHMENT_LABEL,
    )


@account_requests_bp.route("/<int:request_id>/download-summary")
def download_summary(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    if accounts_request.created_by_user_id != current_user.id:
        flash("You can download only your own accounts request summary.", "danger")
        return redirect(url_for("account_requests.list_requests"))
    return render_accounts_request_pdf(accounts_request, "account_admin")


@account_requests_bp.route("/<int:request_id>/submit", methods=["POST"])
def submit_request(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    if accounts_request.created_by_user_id != current_user.id:
        flash("You can submit only your own accounts request.", "danger")
        return redirect(url_for("account_requests.list_requests"))

    try:
        ensure_transition(accounts_request, STATUS_PENDING_APPROVAL)
        accounts_request.status = STATUS_PENDING_APPROVAL
        accounts_request.submitted_at = datetime.utcnow()
        record_action(
            request_obj=accounts_request,
            action_by_user_id=current_user.id,
            action_type="submitted",
            from_status=STATUS_DRAFT,
            to_status=STATUS_PENDING_APPROVAL,
        )
        db.session.commit()
        send_accounts_request_submitted_email(accounts_request)
        flash("Accounts request submitted for approval.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    return redirect(url_for("account_requests.view_request", request_id=request_id))


@account_requests_bp.route("/<int:request_id>/record-expense", methods=["POST"])
def record_expense(request_id):
    current_user = get_current_user()
    accounts_request = AccountsRequest.query.get_or_404(request_id)
    if accounts_request.created_by_user_id != current_user.id:
        flash("You can update only your own accounts request.", "danger")
        return redirect(url_for("account_requests.list_requests"))

    try:
        ensure_transition(accounts_request, STATUS_EXPENSE_RECORDED)
        actual_amount = parse_amount(request.form.get("actual_amount"))
        payment_date_raw = request.form.get("payment_date")
        if not payment_date_raw:
            raise ValueError("Payment date is required.")

        execution_comments = (request.form.get("execution_comments") or "").strip()
        accounts_request.actual_amount = actual_amount
        accounts_request.payment_date = date.fromisoformat(payment_date_raw)
        accounts_request.payment_reference = (request.form.get("payment_reference") or "").strip() or None
        accounts_request.vendor_name = (request.form.get("vendor_name") or "").strip() or accounts_request.vendor_name
        accounts_request.execution_comments = execution_comments or None
        accounts_request.status = STATUS_EXPENSE_RECORDED
        accounts_request.expense_recorded_at = datetime.utcnow()

        attachment_count = add_attachments(
            accounts_request,
            request.files.getlist("expense_attachments"),
            STAGE_POST_EXPENSE,
        )
        if attachment_count == 0:
            raise ValueError("At least one final bill or proof attachment is required.")

        record_action(
            request_obj=accounts_request,
            action_by_user_id=current_user.id,
            action_type="expense_recorded",
            from_status=STATUS_APPROVED,
            to_status=STATUS_EXPENSE_RECORDED,
            comments=execution_comments or None,
        )
        db.session.commit()
        send_accounts_request_ready_for_closure_email(accounts_request)
        send_accounts_request_status_email(
            accounts_request,
            "Accounts Request Expense Details Recorded",
            "Expense details and supporting documents have been recorded for your accounts request.",
        )
        flash("Expense details recorded successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")

    return redirect(url_for("account_requests.view_request", request_id=request_id))
