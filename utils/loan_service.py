from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import asc

from models.db import db
from models.models import EmployeeLoan, EmployeeLoanAction, EmployeeLoanConfig, EmployeeLoanRepayment, User


STATUS_DRAFT = "draft"
STATUS_PENDING_APPROVAL = "pending_approval"
STATUS_REJECTED = "rejected"
STATUS_PENDING_PAYMENT = "pending_payment"
STATUS_PAID = "paid"
STATUS_COMPLETED = "completed"

ALLOWED_TRANSITIONS = {
    STATUS_DRAFT: {STATUS_PENDING_APPROVAL},
    STATUS_PENDING_APPROVAL: {STATUS_REJECTED, STATUS_PENDING_PAYMENT},
    STATUS_PENDING_PAYMENT: {STATUS_PAID},
}


def get_or_create_loan_config() -> EmployeeLoanConfig:
    config = EmployeeLoanConfig.query.order_by(EmployeeLoanConfig.id.asc()).first()
    if config:
        return config

    config = EmployeeLoanConfig()
    db.session.add(config)
    db.session.commit()
    return config


def generate_loan_no() -> str:
    today_prefix = datetime.utcnow().strftime("LOAN-%Y%m%d")
    count_today = EmployeeLoan.query.filter(EmployeeLoan.loan_no.like(f"{today_prefix}-%")).count()
    return f"{today_prefix}-{count_today + 1:04d}"


def parse_amount(value: str | None) -> Decimal:
    try:
        amount = Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("Amount must be a valid number.")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return amount


def parse_installments(value: str | None) -> int:
    try:
        installments = int(value or 0)
    except (TypeError, ValueError):
        raise ValueError("Installments must be a valid whole number.")
    if installments <= 0:
        raise ValueError("Installments must be at least 1.")
    if installments > 60:
        raise ValueError("Installments cannot exceed 60 months.")
    return installments


def parse_optional_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Preferred disbursement date is invalid.") from exc


def parse_repayment_month(value: str | None) -> tuple[int, int]:
    if not value:
        raise ValueError("Repayment start month is required.")
    try:
        year, month = map(int, value.split("-"))
    except Exception as exc:
        raise ValueError("Repayment start month is invalid.") from exc
    if month < 1 or month > 12:
        raise ValueError("Repayment start month is invalid.")
    return month, year


def ensure_transition(loan: EmployeeLoan, next_status: str) -> None:
    allowed = ALLOWED_TRANSITIONS.get(loan.status, set())
    if next_status not in allowed:
        raise ValueError(f"Cannot move employee loan from {loan.status} to {next_status}.")


def record_action(
    loan: EmployeeLoan,
    action_by_user_id: int,
    action_type: str,
    from_status: str | None,
    to_status: str,
    comments: str | None = None,
) -> None:
    db.session.add(
        EmployeeLoanAction(
            employee_loan_id=loan.id,
            action_by_user_id=action_by_user_id,
            action_type=action_type,
            from_status=from_status,
            to_status=to_status,
            comments=comments,
        )
    )


def require_fixed_approver(config: EmployeeLoanConfig | None) -> User:
    if not config or not config.fixed_approver_user_id:
        raise ValueError("Employee loan approver is not configured yet.")
    approver = User.query.get(config.fixed_approver_user_id)
    if not approver:
        raise ValueError("Configured employee loan approver could not be found.")
    return approver


def calculate_monthly_installment(total_amount: Decimal, installments: int) -> Decimal:
    return (total_amount / Decimal(installments)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def has_started_for_month(loan: EmployeeLoan, month: int, year: int) -> bool:
    if not loan.repayment_start_year or not loan.repayment_start_month:
        return False
    return (year, month) >= (loan.repayment_start_year, loan.repayment_start_month)


def repayments_before_month(loan: EmployeeLoan, month: int, year: int) -> list[EmployeeLoanRepayment]:
    repayments = (
        EmployeeLoanRepayment.query.filter_by(employee_loan_id=loan.id)
        .order_by(asc(EmployeeLoanRepayment.payroll_year), asc(EmployeeLoanRepayment.payroll_month))
        .all()
    )
    return [item for item in repayments if (item.payroll_year, item.payroll_month) < (year, month)]


def repayment_for_month(loan: EmployeeLoan, month: int, year: int) -> EmployeeLoanRepayment | None:
    return EmployeeLoanRepayment.query.filter_by(
        employee_loan_id=loan.id,
        payroll_month=month,
        payroll_year=year,
    ).first()


def projected_installment_amount(loan: EmployeeLoan, month: int, year: int) -> Decimal:
    if loan.status not in {STATUS_PAID, STATUS_COMPLETED}:
        return Decimal("0.00")
    if not has_started_for_month(loan, month, year):
        return Decimal("0.00")

    if repayment_for_month(loan, month, year):
        return Decimal(str(repayment_for_month(loan, month, year).deducted_amount or 0)).quantize(Decimal("0.01"))

    previous_repayments = repayments_before_month(loan, month, year)
    if len(previous_repayments) >= int(loan.total_installments or 0):
        return Decimal("0.00")

    approved_amount = Decimal(str(loan.approved_amount or loan.requested_amount or 0)).quantize(Decimal("0.01"))
    paid_amount = sum(Decimal(str(item.deducted_amount or 0)) for item in previous_repayments)
    remaining = (approved_amount - paid_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if remaining <= 0:
        return Decimal("0.00")

    remaining_installments = int(loan.total_installments or 0) - len(previous_repayments)
    if remaining_installments <= 1:
        return remaining
    return min(Decimal(str(loan.monthly_installment or 0)), remaining).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_employee_loan_deduction(employee_id: int, month: int, year: int) -> tuple[Decimal, list[dict]]:
    loans = (
        EmployeeLoan.query.filter_by(employee_id=employee_id)
        .filter(EmployeeLoan.status.in_([STATUS_PAID, STATUS_COMPLETED]))
        .order_by(EmployeeLoan.created_at.asc())
        .all()
    )
    total = Decimal("0.00")
    breakdown = []
    for loan in loans:
        amount = projected_installment_amount(loan, month, year)
        if amount <= 0:
            continue
        total += amount
        previous_repayments = repayments_before_month(loan, month, year)
        breakdown.append(
            {
                "loan_no": loan.loan_no,
                "amount": float(amount),
                "installment_number": len(previous_repayments) + 1,
                "total_installments": loan.total_installments,
                "remaining_after_this": float(
                    max(
                        Decimal("0.00"),
                        Decimal(str(loan.approved_amount or loan.requested_amount or 0))
                        - sum(Decimal(str(item.deducted_amount or 0)) for item in previous_repayments)
                        - amount,
                    )
                ),
            }
        )
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), breakdown


def record_loan_repayments_for_month(month: int, year: int) -> None:
    loans = (
        EmployeeLoan.query.filter_by(status=STATUS_PAID)
        .order_by(EmployeeLoan.created_at.asc())
        .all()
    )
    for loan in loans:
        amount = projected_installment_amount(loan, month, year)
        if amount <= 0:
            continue
        if repayment_for_month(loan, month, year):
            continue

        previous_count = len(repayments_before_month(loan, month, year))
        db.session.add(
            EmployeeLoanRepayment(
                employee_loan_id=loan.id,
                payroll_month=month,
                payroll_year=year,
                installment_number=previous_count + 1,
                deducted_amount=amount,
            )
        )

        if previous_count + 1 >= int(loan.total_installments or 0):
            loan.status = STATUS_COMPLETED
            loan.completed_at = datetime.utcnow()


def summarize_employee_loans(loans: list[EmployeeLoan]) -> dict[str, int]:
    return {
        "draft": sum(1 for loan in loans if loan.status == STATUS_DRAFT),
        "pending": sum(1 for loan in loans if loan.status in {STATUS_PENDING_APPROVAL, STATUS_PENDING_PAYMENT}),
        "active": sum(1 for loan in loans if loan.status == STATUS_PAID),
        "completed": sum(1 for loan in loans if loan.status == STATUS_COMPLETED),
    }


def summarize_manager_loans(loans: list[EmployeeLoan]) -> dict[str, int]:
    return {
        "pending": sum(1 for loan in loans if loan.status == STATUS_PENDING_APPROVAL),
        "approved": sum(1 for loan in loans if loan.status == STATUS_PENDING_PAYMENT),
        "rejected": sum(1 for loan in loans if loan.status == STATUS_REJECTED),
    }


def summarize_account_loans(loans: list[EmployeeLoan]) -> dict[str, int]:
    return {
        "pending_payment": sum(1 for loan in loans if loan.status == STATUS_PENDING_PAYMENT),
        "paid": sum(1 for loan in loans if loan.status == STATUS_PAID),
    }
