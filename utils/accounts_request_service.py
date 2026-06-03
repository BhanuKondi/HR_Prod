from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from models.db import db
from models.models import (
    AccountsRequest,
    AccountsRequestAction,
    AccountsRequestAttachment,
    AccountsRequestConfig,
    AccountsRequestType,
    User,
)


STATUS_DRAFT = "draft"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_EXPENSE_RECORDED = "expense_recorded"
STATUS_CLOSED = "closed"

PAYMENT_MODE_CASH = "cash_withdrawal"
PAYMENT_MODE_DIRECT = "direct_payment"
PAYMENT_MODE_PAY_LANDLORD = "pay_landlord"
PAYMENT_MODE_REIMBURSE_DIRECTOR = "reimburse_director"

DIRECTOR_HOUSE_RENT_TYPE_NAME = "Director House Rent (Owner Expense)"

ALLOWED_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_PENDING_APPROVAL},
    STATUS_PENDING_APPROVAL: {STATUS_APPROVED, STATUS_REJECTED},
    STATUS_APPROVED: {STATUS_EXPENSE_RECORDED},
    STATUS_EXPENSE_RECORDED: {STATUS_CLOSED},
}

ALLOWED_ATTACHMENT_EXTENSIONS = ("pdf", "png", "jpg", "jpeg", "webp")
ALLOWED_ATTACHMENT_ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp"
ALLOWED_ATTACHMENT_LABEL = "PDF, PNG, JPG, JPEG, and WEBP"
STAGE_PRE_APPROVAL = "pre_approval"
STAGE_POST_EXPENSE = "post_expense"


def seed_accounts_request_types() -> None:
    defaults = [
        ("Cash Request", "Cash withdrawal needed for office expenses"),
        ("Utility Bill", "Office utility bill payment and approval"),
        ("Office Purchase", "Office purchase requiring company funds"),
        ("Miscellaneous Expense", "Other approved company operational expenses"),
        (
            DIRECTOR_HOUSE_RENT_TYPE_NAME,
            "Owner/director housing rent expense with landlord or reimbursement payment option.",
        ),
    ]
    existing = {item.name.lower() for item in AccountsRequestType.query.all()}
    changed = False
    for name, description in defaults:
        if name.lower() in existing:
            continue
        db.session.add(AccountsRequestType(name=name, description=description, is_active=True))
        changed = True
    if changed:
        db.session.commit()


def get_accounts_request_config() -> AccountsRequestConfig | None:
    return AccountsRequestConfig.query.order_by(AccountsRequestConfig.id.asc()).first()


def generate_request_no() -> str:
    today_prefix = datetime.utcnow().strftime("ACR-%Y%m%d")
    count_today = AccountsRequest.query.filter(
        AccountsRequest.request_no.like(f"{today_prefix}-%")
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


def ensure_transition(request_obj: AccountsRequest, next_status: str) -> None:
    allowed_next = ALLOWED_TRANSITIONS.get(request_obj.status, set())
    if next_status not in allowed_next:
        raise ValueError(f"Cannot move accounts request from {request_obj.status} to {next_status}.")


def record_action(
    request_obj: AccountsRequest,
    action_by_user_id: int,
    action_type: str,
    from_status: str | None,
    to_status: str,
    comments: str | None = None,
) -> None:
    db.session.add(
        AccountsRequestAction(
            accounts_request_id=request_obj.id,
            action_by_user_id=action_by_user_id,
            action_type=action_type,
            from_status=from_status,
            to_status=to_status,
            comments=comments,
        )
    )


def upload_dir() -> str:
    return os.path.join(current_app.static_folder, "uploads", "accounts_requests")


def save_attachment(file_storage: FileStorage, request_no: str) -> tuple[str, str]:
    filename = secure_filename(file_storage.filename or "")
    if not filename or "." not in filename:
        raise ValueError("Attachment file is invalid.")
    extension = filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise ValueError(f"Only {ALLOWED_ATTACHMENT_LABEL} files are allowed.")

    directory = upload_dir()
    os.makedirs(directory, exist_ok=True)
    stored_name = secure_filename(f"{request_no}_{datetime.utcnow().strftime('%H%M%S%f')}.{extension}")
    absolute_path = os.path.join(directory, stored_name)
    file_storage.save(absolute_path)
    relative_path = os.path.join("uploads", "accounts_requests", stored_name).replace("\\", "/")
    return filename, relative_path


def add_attachments(request_obj: AccountsRequest, files: list[FileStorage], stage: str) -> int:
    added = 0
    for attachment in files:
        if not attachment or not attachment.filename:
            continue
        original_name, relative_path = save_attachment(attachment, request_obj.request_no)
        db.session.add(
            AccountsRequestAttachment(
                accounts_request_id=request_obj.id,
                attachment_stage=stage,
                file_name=original_name,
                file_path=relative_path,
                mime_type=attachment.mimetype,
            )
        )
        added += 1
    return added


def require_configured_approver(config: AccountsRequestConfig | None) -> User:
    if not config or not config.default_approver_user_id:
        raise ValueError("Accounts request approver is not configured yet.")
    approver = User.query.get(config.default_approver_user_id)
    if not approver:
        raise ValueError("Configured accounts approver could not be found.")
    return approver
