import calendar
import shutil
from io import BytesIO

import inflect
import pdfkit
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from sqlalchemy import extract, func

from models.db import db
from models.models import (
    Attendance,
    EmployeeAccount,
    EmployeeSalary,
    Holiday,
    Leavee,
    PayrollDetails,
    PayrollRun,
)
from utils.authz import ROLE_EMPLOYEE, get_current_employee, require_roles
from utils.loan_service import get_employee_loan_deduction


employee_payroll_bp = Blueprint(
    "employee_payroll",
    __name__,
    url_prefix="/employee/payroll",
)


@employee_payroll_bp.before_request
def enforce_employee_role():
    return require_roles(ROLE_EMPLOYEE)


def get_pdf_config():
    wkhtmltopdf_path = shutil.which("wkhtmltopdf")
    if not wkhtmltopdf_path:
        raise RuntimeError(
            "wkhtmltopdf is not installed or not on PATH. Install it to enable payslip PDF downloads."
        )
    return pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)


def number_to_words(amount):
    engine = inflect.engine()
    is_negative = amount < 0
    amount = abs(amount)

    integer_part = int(amount)
    decimal_part = round((amount - integer_part) * 100)

    words = engine.number_to_words(integer_part, andword="")
    result = f"{words} rupees"

    if decimal_part > 0:
        result += f" and {decimal_part:02d} paise"

    if is_negative:
        result = f"minus {result}"

    return result


def count_sundays(year, month):
    cal = calendar.Calendar()
    return sum(
        1
        for day in cal.itermonthdates(year, month)
        if day.month == month and day.weekday() == 6
    )


def count_holidays(year, month):
    return Holiday.query.filter(
        extract("month", Holiday.date) == month,
        extract("year", Holiday.date) == year,
    ).count()


def get_employee_or_logout():
    employee = get_current_employee()
    if employee:
        return employee

    flash("Employee profile not found.", "danger")
    return None


@employee_payroll_bp.route("/payslip", methods=["GET"])
def payslip_page():
    employee = get_employee_or_logout()
    if not employee:
        return redirect(url_for("auth.logout"))
    return render_template("employee/payslip.html", employee=employee)


@employee_payroll_bp.route("/download", methods=["POST"])
def download_payslip():
    employee = get_employee_or_logout()
    if not employee:
        return redirect(url_for("auth.logout"))

    pay_month = request.form.get("pay_month")
    if not pay_month:
        flash("Please select a month.", "warning")
        return redirect(url_for("employee_payroll.payslip_page"))

    year, month = map(int, pay_month.split("-"))

    payrun = PayrollRun.query.filter_by(month=month, year=year, approved=True).first()
    if not payrun:
        flash("Payslip not available yet. Payroll not approved.", "warning")
        return redirect(url_for("employee_payroll.payslip_page"))

    salary = EmployeeSalary.query.filter_by(employee_id=employee.id).first()
    account = EmployeeAccount.query.filter_by(employee_id=employee.id).first()
    if not salary:
        flash("Salary details not found.", "danger")
        return redirect(url_for("employee_payroll.payslip_page"))

    total_days = calendar.monthrange(year, month)[1]
    sundays = count_sundays(year, month)
    holidays = count_holidays(year, month)
    total_working_days = max(1, total_days - sundays - holidays)

    attendance_days = db.session.query(
        func.count(func.distinct(Attendance.date))
    ).filter(
        Attendance.user_id == employee.user_id,
        extract("month", Attendance.date) == month,
        extract("year", Attendance.date) == year,
        Attendance.duration_seconds >= 1,
    ).scalar() or 0

    paid_leave_days = db.session.query(
        func.coalesce(func.sum(Leavee.total_days), 0)
    ).filter(
        Leavee.emp_code == employee.emp_code,
        Leavee.leave_type.in_(["Casual Leave", "Sick Leave"]),
        Leavee.status == "Approved",
        extract("month", Leavee.start_date) == month,
        extract("year", Leavee.start_date) == year,
    ).scalar() or 0

    lwp_days = db.session.query(
        func.coalesce(func.sum(Leavee.total_days), 0)
    ).filter(
        Leavee.emp_code == employee.emp_code,
        Leavee.leave_type == "Leave Without Pay",
        Leavee.status == "Approved",
        extract("month", Leavee.start_date) == month,
        extract("year", Leavee.start_date) == year,
    ).scalar() or 0

    present_days = int(attendance_days + paid_leave_days)
    lwp_days = int(lwp_days)
    absent_days = max(0, total_working_days - present_days - lwp_days)
    absent_and_lwp = absent_days + lwp_days

    monthly_salary = float(salary.gross_salary) / 12
    salary_per_day = round(monthly_salary / total_working_days, 2)
    earned_salary = round(present_days * salary_per_day, 2)
    lwp_deduction = round(absent_and_lwp * salary_per_day, 2)

    payroll = PayrollDetails.query.filter_by(
        employee_id=employee.id,
        month=month,
        year=year,
    ).first()
    bonus = payroll.bonus if payroll and payroll.bonus else 0
    deduction = payroll.deduction if payroll and payroll.deduction else 0
    comment = payroll.comments if payroll and payroll.comments else ""
    loan_deduction_decimal, loan_breakdown = get_employee_loan_deduction(employee.id, month, year)
    loan_deduction = float(loan_deduction_decimal)

    net_pay = monthly_salary + bonus - deduction - lwp_deduction - loan_deduction
    earnings = [
        ("Basic", salary.basic_percent),
        ("HRA", salary.hra_percent),
        ("Fixed Allowance", salary.fixed_allowance),
        ("Medical Reimbursement", salary.medical_fixed),
        ("Driver Reimbursement", salary.driver_reimbursement),
        ("EPF", salary.epf_percent),
    ]

    context = {
        "company_name": "ATIKES",
        "company_address": "#4-36/1, Near Railway Station, Gopalapatnam, Andhra Pradesh 533408",
        "employee_name": f"{employee.first_name} {employee.last_name}",
        "designation": employee.job_title,
        "employee_id": employee.emp_code,
        "date_of_joining": employee.date_of_joining.strftime("%d-%m-%Y"),
        "pay_period": f"{calendar.month_name[month]} {year}",
        "pay_date": payrun.approved_at.strftime("%d-%m-%Y"),
        "bank_account": account.account_number if account else "-",
        "total_working_days": total_working_days,
        "paid_days": present_days,
        "lop_days": lwp_days,
        "absent_days": absent_days,
        "earnings": earnings,
        "gross_salary": monthly_salary,
        "earned_salary": earned_salary,
        "lwp_deduction": lwp_deduction,
        "bonus": bonus,
        "deduction": deduction,
        "loan_deduction": loan_deduction,
        "loan_breakdown": loan_breakdown,
        "comment": comment,
        "net_pay": net_pay,
        "amount_in_words": number_to_words(net_pay),
        "basic": round(((salary.basic_percent / 100) * salary.gross_salary) / 12, 2),
        "hra": round(((salary.hra_percent / 100) * salary.gross_salary) / 12, 2),
        "fixed_allowance": round(((salary.fixed_allowance / 100) * salary.gross_salary) / 12, 2),
    }

    rendered_html = render_template("employee/payslip_pdf.html", **context)
    pdf_options = {
        "page-size": "A4",
        "encoding": "UTF-8",
        "enable-local-file-access": None,
    }

    try:
        pdf_bytes = pdfkit.from_string(
            rendered_html,
            False,
            options=pdf_options,
            configuration=get_pdf_config(),
        )
    except RuntimeError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("employee_payroll.payslip_page"))

    return send_file(
        BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f"Payslip_{employee.emp_code}_{month}_{year}.pdf",
        mimetype="application/pdf",
    )
