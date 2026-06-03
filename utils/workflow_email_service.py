from __future__ import annotations

from flask import current_app, request

from models.models import User
from utils.authz import ROLE_ACCOUNT_ADMIN, get_role_by_name
from utils.email_service import send_email


def _base_url() -> str:
    configured = current_app.config.get("APP_BASE_URL") or current_app.config.get("BASE_URL")
    if configured:
        return str(configured).rstrip("/")
    try:
        return request.url_root.rstrip("/")
    except RuntimeError:
        return "http://127.0.0.1:5051"


def _safe_user_label(user) -> str:
    if not user:
        return "User"
    return getattr(user, "display_name", None) or getattr(user, "email", None) or "User"


def _safe_email(user) -> str | None:
    return getattr(user, "email", None) if user else None


def _account_admin_recipients() -> list[str]:
    role = get_role_by_name(ROLE_ACCOUNT_ADMIN)
    if not role:
        return []
    users = User.query.filter_by(role_id=role.id, is_active=True).all()
    return [user.email for user in users if user.email]


def send_reimbursement_submitted_email(reimbursement) -> None:
    approver_email = _safe_email(reimbursement.manager_approver)
    if not approver_email:
        return
    send_email(
        "Reimbursement Request Submitted - Action Required",
        [approver_email],
        f"""
Hello,

A reimbursement request has been submitted and requires your approval.

Request No     : {reimbursement.request_no}
Employee       : {reimbursement.employee.first_name} {reimbursement.employee.last_name}
Type           : {reimbursement.reimbursement_type.name if reimbursement.reimbursement_type else '-'}
Requested Amt  : {float(reimbursement.requested_amount or 0):.2f}
Bill Date      : {reimbursement.bill_date}

Open the request here:
{_base_url()}/manager/reimbursements/{reimbursement.id}

Regards,
ATIKES
""",
    )


def send_reimbursement_pending_finance_email(reimbursement) -> None:
    recipients = _account_admin_recipients()
    if recipients:
        send_email(
            "Reimbursement Pending Finance Review",
            recipients,
            f"""
Hello,

A reimbursement request is now pending finance review.

Request No            : {reimbursement.request_no}
Employee              : {reimbursement.employee.first_name} {reimbursement.employee.last_name}
Requested Amount      : {float(reimbursement.requested_amount or 0):.2f}
Manager Approved Amt  : {float(reimbursement.manager_approved_amount or 0):.2f}

Open the finance queue here:
{_base_url()}/accounts/reimbursements/{reimbursement.id}

Regards,
ATIKES
""",
        )

    employee_email = _safe_email(reimbursement.employee.user if reimbursement.employee else None)
    if employee_email:
        send_email(
            "Reimbursement Moved To Finance Review",
            [employee_email],
            f"""
Hello,

Your reimbursement request has been approved by {_safe_user_label(reimbursement.manager_approver)} and moved to finance review.

Request No           : {reimbursement.request_no}
Requested Amount     : {float(reimbursement.requested_amount or 0):.2f}
Manager Approved Amt : {float(reimbursement.manager_approved_amount or 0):.2f}

You can track it here:
{_base_url()}/employee/reimbursements/{reimbursement.id}

Regards,
ATIKES
""",
        )


def send_reimbursement_status_email(reimbursement, subject: str, message: str) -> None:
    employee_email = _safe_email(reimbursement.employee.user if reimbursement.employee else None)
    if not employee_email:
        return
    send_email(
        subject,
        [employee_email],
        f"""
Hello,

{message}

Request No      : {reimbursement.request_no}
Type            : {reimbursement.reimbursement_type.name if reimbursement.reimbursement_type else '-'}
Requested Amt   : {float(reimbursement.requested_amount or 0):.2f}
Final Amount    : {float(reimbursement.final_amount or 0):.2f}
Current Status  : {reimbursement.status.replace('_', ' ').title()}

Track it here:
{_base_url()}/employee/reimbursements/{reimbursement.id}

Regards,
ATIKES
""",
    )


def send_accounts_request_submitted_email(accounts_request) -> None:
    approver_email = _safe_email(accounts_request.approver)
    if not approver_email:
        return

    approver_path = (
        f"/manager/accounts/requests/{accounts_request.id}"
        if accounts_request.approver and accounts_request.approver.employee
        else f"/admin/accounts/requests/{accounts_request.id}"
    )
    send_email(
        "Accounts Request Submitted - Action Required",
        [approver_email],
        f"""
Hello,

A new accounts request has been submitted and requires your approval.

Request No      : {accounts_request.request_no}
Submitted By    : {_safe_user_label(accounts_request.created_by)}
Type            : {accounts_request.request_type.name if accounts_request.request_type else '-'}
Requested Amt   : {float(accounts_request.requested_amount or 0):.2f}
Title           : {accounts_request.title}

Review it here:
{_base_url()}{approver_path}

Regards,
ATIKES
""",
    )


def send_accounts_request_status_email(accounts_request, subject: str, message: str) -> None:
    requester_email = _safe_email(accounts_request.created_by)
    if not requester_email:
        return
    send_email(
        subject,
        [requester_email],
        f"""
Hello,

{message}

Request No      : {accounts_request.request_no}
Type            : {accounts_request.request_type.name if accounts_request.request_type else '-'}
Requested Amt   : {float(accounts_request.requested_amount or 0):.2f}
Approved Amt    : {float(accounts_request.approved_amount or 0):.2f}
Actual Amt      : {float(accounts_request.actual_amount or 0):.2f}
Current Status  : {accounts_request.status.replace('_', ' ').title()}

Open it here:
{_base_url()}/accounts/requests/{accounts_request.id}

Regards,
ATIKES
""",
    )


def send_accounts_request_ready_for_closure_email(accounts_request) -> None:
    approver_email = _safe_email(accounts_request.approver)
    if not approver_email:
        return

    approver_path = (
        f"/manager/accounts/requests/{accounts_request.id}"
        if accounts_request.approver and accounts_request.approver.employee
        else f"/admin/accounts/requests/{accounts_request.id}"
    )
    send_email(
        "Accounts Request Ready For Closure Review",
        [approver_email],
        f"""
Hello,

An approved accounts request now has expense details recorded and is ready for your closure review.

Request No      : {accounts_request.request_no}
Submitted By    : {_safe_user_label(accounts_request.created_by)}
Approved Amt    : {float(accounts_request.approved_amount or 0):.2f}
Actual Amt      : {float(accounts_request.actual_amount or 0):.2f}

Review it here:
{_base_url()}{approver_path}

Regards,
ATIKES
""",
    )


def _loan_approver_path(loan) -> str:
    approver = getattr(loan, "approver", None)
    if not approver:
        return "/login"
    role_name = getattr(getattr(approver, "role", None), "name", "")
    normalized = str(role_name or "").lower().replace(" ", "_")
    if normalized == "admin":
        return f"/admin/loans/{loan.id}"
    return f"/manager/loans/{loan.id}"


def send_loan_submitted_email(loan) -> None:
    approver_email = _safe_email(loan.approver)
    if not approver_email:
        return
    send_email(
        "Employee Loan Request Submitted - Action Required",
        [approver_email],
        f"""
Hello,

A new employee loan request has been submitted and requires your approval.

Loan No           : {loan.loan_no}
Employee          : {loan.employee.first_name} {loan.employee.last_name}
Requested Amount  : {float(loan.requested_amount or 0):.2f}
Installments      : {loan.total_installments}
Reason            : {loan.reason}

Review it here:
{_base_url()}{_loan_approver_path(loan)}

Regards,
ATIKES
""",
    )


def send_loan_pending_payment_email(loan) -> None:
    recipients = _account_admin_recipients()
    if recipients:
        send_email(
            "Employee Loan Approved - Payment Required",
            recipients,
            f"""
Hello,

An employee loan request has been approved and now requires payment processing.

Loan No           : {loan.loan_no}
Employee          : {loan.employee.first_name} {loan.employee.last_name}
Approved Amount   : {float(loan.approved_amount or loan.requested_amount or 0):.2f}
Installments      : {loan.total_installments}

Open the payment queue here:
{_base_url()}/accounts/loans/{loan.id}

Regards,
ATIKES
""",
        )

    employee_email = _safe_email(loan.employee.user if loan.employee else None)
    if employee_email:
        send_email(
            "Employee Loan Approved",
            [employee_email],
            f"""
Hello,

Your employee loan request has been approved and moved to finance for payment.

Loan No           : {loan.loan_no}
Approved Amount   : {float(loan.approved_amount or loan.requested_amount or 0):.2f}
Installments      : {loan.total_installments}

Track it here:
{_base_url()}/employee/loans/{loan.id}

Regards,
ATIKES
""",
        )


def send_loan_status_email(loan, subject: str, message: str) -> None:
    recipients = []
    employee_email = _safe_email(loan.employee.user if loan.employee else None)
    if employee_email:
        recipients.append(employee_email)
    approver_email = _safe_email(loan.approver)
    if approver_email and approver_email not in recipients:
        recipients.append(approver_email)
    if not recipients:
        return

    send_email(
        subject,
        recipients,
        f"""
Hello,

{message}

Loan No           : {loan.loan_no}
Employee          : {loan.employee.first_name} {loan.employee.last_name}
Requested Amount  : {float(loan.requested_amount or 0):.2f}
Approved Amount   : {float(loan.approved_amount or 0):.2f}
Installments      : {loan.total_installments}
Current Status    : {loan.status.replace('_', ' ').title()}

Open it here:
{_base_url()}/employee/loans/{loan.id}

Regards,
ATIKES
""",
    )
