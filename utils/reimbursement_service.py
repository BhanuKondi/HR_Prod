from __future__ import annotations

import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from models.db import db
from models.models import (
    Employee,
    ReimbursementAction,
    ReimbursementAttachment,
    ReimbursementConfig,
    ReimbursementRequest,
    ReimbursementType,
    User,
)
from utils.authz import ROLE_ACCOUNT_ADMIN, get_role_by_name


STATUS_DRAFT = "draft"
STATUS_PENDING_MANAGER = "pending_manager"
STATUS_REJECTED_MANAGER = "rejected_by_manager"
STATUS_PENDING_FINANCE = "pending_finance"
STATUS_REJECTED_FINANCE = "rejected_by_finance"
STATUS_APPROVED_FOR_PAYMENT = "approved_for_payment"
STATUS_PAID = "paid"

ALLOWED_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_PENDING_MANAGER},
    STATUS_PENDING_MANAGER: {STATUS_REJECTED_MANAGER, STATUS_PENDING_FINANCE},
    STATUS_PENDING_FINANCE: {STATUS_REJECTED_FINANCE, STATUS_APPROVED_FOR_PAYMENT},
    STATUS_APPROVED_FOR_PAYMENT: {STATUS_PAID},
}

ALLOWED_ATTACHMENT_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "webp")
ALLOWED_ATTACHMENT_ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp"
ALLOWED_ATTACHMENT_LABEL = "PDF, PNG, JPG, JPEG, and WEBP"
DIRECTOR_HOUSE_RENT_TYPE_NAME = "Director House Rent (Owner Expense)"


def get_or_create_reimbursement_config() -> ReimbursementConfig:
    config = ReimbursementConfig.query.order_by(ReimbursementConfig.id.asc()).first()
    if config:
        return config

    config = ReimbursementConfig()
    db.session.add(config)
    db.session.commit()
    return config


def seed_reimbursement_types() -> None:
    defaults = [
        ("Travel", "Taxi, mileage, and business travel claims"),
        ("Food", "Business meals and approved team expenses"),
        ("Internet", "Approved internet or connectivity reimbursement"),
        ("Medical", "Medical reimbursement as per company policy"),
        ("Office Supplies", "Work-related office supply purchases"),
        (
            DIRECTOR_HOUSE_RENT_TYPE_NAME,
            "Director/owner house-rent expense with landlord or reimbursement proofs.",
        ),
    ]
    existing = {item.name.lower() for item in ReimbursementType.query.all()}
    changed = False
    for name, description in defaults:
        if name.lower() in existing:
            continue
        db.session.add(ReimbursementType(name=name, description=description, is_active=True))
        changed = True
    if changed:
        db.session.commit()


def generate_request_no() -> str:
    today_prefix = datetime.utcnow().strftime("RMB-%Y%m%d")
    count_today = ReimbursementRequest.query.filter(
        ReimbursementRequest.request_no.like(f"{today_prefix}-%")
    ).count()
    return f"{today_prefix}-{count_today + 1:04d}"


def parse_amount(value: str | None) -> Decimal:
    try:
        amount = Decimal(str(value or "0")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Amount must be a valid number.")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return amount


def parse_bill_date(value: str | None) -> date:
    if not value:
        raise ValueError("Bill date is required.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Bill date is invalid.") from exc


def resolve_manager_approver(employee: Employee, config: ReimbursementConfig) -> User | None:
    if config.approver_mode == "fixed_approver" and config.fixed_approver_user_id:
        return User.query.get(config.fixed_approver_user_id)
    if employee.manager and employee.manager.user:
        return employee.manager.user
    return None


def is_director_house_rent_type(reimbursement_type_id: int | None) -> bool:
    if not reimbursement_type_id:
        return False
    reimbursement_type = ReimbursementType.query.get(reimbursement_type_id)
    if not reimbursement_type or not reimbursement_type.name:
        return False
    return reimbursement_type.name.strip().lower() == DIRECTOR_HOUSE_RENT_TYPE_NAME.lower()


def resolve_account_admin_approver(exclude_user_id: int | None = None) -> User | None:
    account_admin_role = get_role_by_name(ROLE_ACCOUNT_ADMIN)
    if not account_admin_role:
        return None
    query = User.query.filter_by(role_id=account_admin_role.id, is_active=True)
    if exclude_user_id:
        candidate = (
            query.filter(User.id != exclude_user_id)
            .order_by(User.display_name.asc(), User.email.asc(), User.id.asc())
            .first()
        )
        if candidate:
            return candidate
    return query.order_by(User.display_name.asc(), User.email.asc(), User.id.asc()).first()


def ensure_transition(request_obj: ReimbursementRequest, next_status: str) -> None:
    allowed_next = ALLOWED_TRANSITIONS.get(request_obj.status, set())
    if next_status not in allowed_next:
        raise ValueError(f"Cannot move reimbursement from {request_obj.status} to {next_status}.")


def record_action(
    request_obj: ReimbursementRequest,
    action_by_user_id: int,
    action_type: str,
    from_status: str | None,
    to_status: str,
    comments: str | None = None,
) -> None:
    db.session.add(
        ReimbursementAction(
            reimbursement_request_id=request_obj.id,
            action_by_user_id=action_by_user_id,
            action_type=action_type,
            from_status=from_status,
            to_status=to_status,
            comments=comments,
        )
    )


def reimbursement_upload_dir() -> str:
    return os.path.join(current_app.static_folder, "uploads", "reimbursements")


def save_attachment(file_storage: FileStorage, request_no: str) -> tuple[str, str]:
    filename = secure_filename(file_storage.filename or "")
    if not filename or "." not in filename:
        raise ValueError("Attachment file is invalid.")
    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(f"Only {ALLOWED_ATTACHMENT_LABEL} files are allowed.")

    directory = reimbursement_upload_dir()
    os.makedirs(directory, exist_ok=True)
    stored_name = secure_filename(f"{request_no}_{datetime.utcnow().strftime('%H%M%S%f')}.{extension}")
    absolute_path = os.path.join(directory, stored_name)
    file_storage.save(absolute_path)
    relative_path = os.path.join("uploads", "reimbursements", stored_name).replace("\\", "/")
    return filename, relative_path


def add_attachments(request_obj: ReimbursementRequest, files: list[FileStorage]) -> int:
    added = 0
    for attachment in files:
        if not attachment or not attachment.filename:
            continue
        original_name, relative_path = save_attachment(attachment, request_obj.request_no)
        db.session.add(
            ReimbursementAttachment(
                reimbursement_request_id=request_obj.id,
                file_name=original_name,
                file_path=relative_path,
                mime_type=attachment.mimetype,
            )
        )
        added += 1
    return added


def summarize_employee_reimbursements(reimbursements: list[ReimbursementRequest]) -> dict[str, int]:
    return {
        "draft": sum(1 for item in reimbursements if item.status == STATUS_DRAFT),
        "pending": sum(1 for item in reimbursements if item.status in {STATUS_PENDING_MANAGER, STATUS_PENDING_FINANCE}),
        "approved": sum(1 for item in reimbursements if item.status == STATUS_APPROVED_FOR_PAYMENT),
        "paid": sum(1 for item in reimbursements if item.status == STATUS_PAID),
    }


def summarize_manager_reimbursements(reimbursements: list[ReimbursementRequest]) -> dict[str, int]:
    return {
        "pending": sum(1 for item in reimbursements if item.status == STATUS_PENDING_MANAGER),
        "approved": sum(1 for item in reimbursements if item.status == STATUS_PENDING_FINANCE),
        "rejected": sum(1 for item in reimbursements if item.status == STATUS_REJECTED_MANAGER),
    }


def summarize_account_reimbursements(reimbursements: list[ReimbursementRequest]) -> dict[str, int]:
    return {
        "pending": sum(1 for item in reimbursements if item.status == STATUS_PENDING_FINANCE),
        "ready_to_pay": sum(1 for item in reimbursements if item.status == STATUS_APPROVED_FOR_PAYMENT),
        "paid": sum(1 for item in reimbursements if item.status == STATUS_PAID),
    }


def summarize_admin_reimbursement_reports(reimbursements: list[ReimbursementRequest]) -> dict[str, int]:
    return {
        "submitted": sum(1 for item in reimbursements if item.status in {STATUS_PENDING_MANAGER, STATUS_PENDING_FINANCE}),
        "approved": sum(1 for item in reimbursements if item.status == STATUS_APPROVED_FOR_PAYMENT),
        "paid": sum(1 for item in reimbursements if item.status == STATUS_PAID),
        "rejected": sum(1 for item in reimbursements if item.status in {STATUS_REJECTED_MANAGER, STATUS_REJECTED_FINANCE}),
    }
