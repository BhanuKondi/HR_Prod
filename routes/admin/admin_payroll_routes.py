import calendar
from datetime import datetime

from flask import Blueprint, jsonify, flash, redirect, render_template, request, url_for
from sqlalchemy import extract, func

from models.attendance import Attendance
from models.db import db
from models.models import Employee, EmployeeSalary, Leavee, PayrollDetails, PayrollRun
from utils.authz import ROLE_ADMIN, require_roles
from utils.loan_service import get_employee_loan_deduction, record_loan_repayments_for_month


admin_payroll_bp = Blueprint(
    "admin_payroll",
    __name__,
    url_prefix="/admin/payroll",
)


@admin_payroll_bp.before_request
def enforce_admin_role():
    return require_roles(ROLE_ADMIN)


def count_weekends(year, month):
    cal = calendar.Calendar()
    return sum(
        1
        for day in cal.itermonthdates(year, month)
        if day.month == month and day.weekday() in (5, 6)
    ).count()


def get_total_working_days(year, month):
    total_days = calendar.monthrange(year, month)[1]
    working_days = total_days - count_weekends(year, month)
    return max(1, working_days)


def get_payrun(month, year):
    return PayrollRun.query.filter_by(month=month, year=year).first()


def get_adjustment_record(employee_id, month, year):
    return PayrollDetails.query.filter_by(
        employee_id=employee_id,
        month=month,
        year=year,
    ).first()


def compute_salary_components(salary: EmployeeSalary):
    monthly_gross = round(float(salary.gross_salary or 0) / 12, 2)
    basic_percent = float(salary.basic_percent or 0)
    hra_percent = float(salary.hra_percent or 0)
    epf_percent = float(salary.epf_percent or 0)

    basic = round(monthly_gross * (basic_percent / 100), 2)
    hra = round(basic * (hra_percent / 100), 2)
    fixed_allowance = round(float(salary.fixed_allowance or 0), 2)
    medical = round(float(salary.medical_fixed or 0), 2)
    driver = round(float(salary.driver_reimbursement or 0), 2)

    special_allowance = round(monthly_gross - (basic + hra + fixed_allowance + medical + driver), 2)
    if special_allowance < 0:
        special_allowance = 0.0

    # EPF with standard statutory wage ceiling assumption (₹15,000 wage base)
    pf_wage_base = min(basic, 15000.0)
    employee_pf = round(pf_wage_base * (epf_percent / 100), 2)
    employer_pf = round(employee_pf, 2)
    gratuity_provision = round(basic * 0.0481, 2)

    return {
        "monthly_gross": monthly_gross,
        "basic": basic,
        "hra": hra,
        "fixed_allowance": fixed_allowance,
        "medical_allowance": medical,
        "driver_reimbursement": driver,
        "special_allowance": special_allowance,
        "employee_pf": employee_pf,
        "employer_pf": employer_pf,
        "gratuity_provision": gratuity_provision,
        # place-holders (future configurable)
        "professional_tax": 0.0,
        "esi": 0.0,
        "tds": 0.0,
    }


def calculate_employee_payroll(employee, month, year, total_working_days):
    salary = EmployeeSalary.query.filter_by(employee_id=employee.id).first()
    if not salary:
        return None

    attendance_days = db.session.query(
        func.count(func.distinct(Attendance.date))
    ).filter(
        Attendance.user_id == employee.user_id,
        extract("month", Attendance.date) == month,
        extract("year", Attendance.date) == year,
        Attendance.duration_seconds >= 5,
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

    components = compute_salary_components(salary)
    monthly_salary = components["monthly_gross"]
    salary_per_day = round(monthly_salary / total_working_days, 2)
    lwp_deduction = round(lwp_days * salary_per_day, 2)
    absent_deduction = round(absent_days * salary_per_day, 2)
    loan_deduction_decimal, loan_breakdown = get_employee_loan_deduction(employee.id, month, year)
    loan_deduction = round(float(loan_deduction_decimal), 2)
    statutory_deductions = round(
        components["employee_pf"] + components["professional_tax"] + components["esi"] + components["tds"], 2
    )
    total_deductions = round(lwp_deduction + absent_deduction + loan_deduction + statutory_deductions, 2)
    base_net_salary = round(monthly_salary - total_deductions, 2)

    payroll = get_adjustment_record(employee.id, month, year)
    if not payroll:
        payroll = PayrollDetails(
            employee_id=employee.id,
            month=month,
            year=year,
            net_salary=base_net_salary,
            bonus=0,
            deduction=0,
            final_salary=base_net_salary,
            comments="",
        )
        db.session.add(payroll)
    else:
        payroll.net_salary = base_net_salary

    bonus = payroll.bonus or 0
    deduction = payroll.deduction or 0
    payroll.final_salary = round(base_net_salary + bonus - deduction, 2)

    return {
        "emp_code": employee.emp_code,
        "name": f"{employee.first_name} {employee.last_name}",
        "salary_month": f"{calendar.month_name[month]} {year}",
        "total_working_days": total_working_days,
        "attendance_days": attendance_days,
        "paid_leave_days": float(paid_leave_days),
        "present_days": present_days,
        "lwp_days": lwp_days,
        "absent_days": absent_days,
        "monthly_salary": monthly_salary,
        "basic": components["basic"],
        "hra": components["hra"],
        "special_allowance": components["special_allowance"],
        "fixed_allowance": components["fixed_allowance"],
        "medical_allowance": components["medical_allowance"],
        "driver_reimbursement": components["driver_reimbursement"],
        "salary_per_day": salary_per_day,
        "lwp_deduction": lwp_deduction,
        "absent_deduction": absent_deduction,
        "loan_deduction": loan_deduction,
        "employee_pf": components["employee_pf"],
        "professional_tax": components["professional_tax"],
        "esi": components["esi"],
        "tds": components["tds"],
        "total_deductions": total_deductions,
        "net_salary": base_net_salary,
        "employer_pf": components["employer_pf"],
        "gratuity_provision": components["gratuity_provision"],
        "employer_monthly_cost": round(
            monthly_salary + components["employer_pf"] + components["gratuity_provision"], 2
        ),
        "bonus": bonus,
        "deduction": deduction,
        "comments": payroll.comments or "",
        "loan_summary": ", ".join(
            f"{item['loan_no']} ({item['installment_number']}/{item['total_installments']})"
            for item in loan_breakdown
        ),
        "final_salary": payroll.final_salary,
    }


def serialize_saved_payroll(employee, payroll, month, year):
    salary = EmployeeSalary.query.filter_by(employee_id=employee.id).first()
    components = compute_salary_components(salary) if salary else {
        "monthly_gross": payroll.net_salary,
        "basic": 0.0,
        "hra": 0.0,
        "special_allowance": 0.0,
        "fixed_allowance": 0.0,
        "medical_allowance": 0.0,
        "driver_reimbursement": 0.0,
        "employee_pf": 0.0,
        "professional_tax": 0.0,
        "esi": 0.0,
        "tds": 0.0,
        "employer_pf": 0.0,
        "gratuity_provision": 0.0,
    }
    total_deductions = round(
        float(components["employee_pf"] or 0)
        + float(components["professional_tax"] or 0)
        + float(components["esi"] or 0)
        + float(components["tds"] or 0),
        2,
    )
    return {
        "emp_code": employee.emp_code,
        "name": f"{employee.first_name} {employee.last_name}",
        "salary_month": f"{calendar.month_name[month]} {year}",
        "total_working_days": "-",
        "attendance_days": "-",
        "paid_leave_days": "-",
        "present_days": "-",
        "lwp_days": "-",
        "absent_days": "-",
        "monthly_salary": components["monthly_gross"],
        "basic": components["basic"],
        "hra": components["hra"],
        "special_allowance": components["special_allowance"],
        "fixed_allowance": components["fixed_allowance"],
        "medical_allowance": components["medical_allowance"],
        "driver_reimbursement": components["driver_reimbursement"],
        "salary_per_day": "-",
        "lwp_deduction": "-",
        "absent_deduction": "-",
        "loan_deduction": float(get_employee_loan_deduction(employee.id, month, year)[0]),
        "employee_pf": components["employee_pf"],
        "professional_tax": components["professional_tax"],
        "esi": components["esi"],
        "tds": components["tds"],
        "total_deductions": total_deductions,
        "net_salary": payroll.net_salary,
        "employer_pf": components["employer_pf"],
        "gratuity_provision": components["gratuity_provision"],
        "employer_monthly_cost": round(
            float(components["monthly_gross"] or 0)
            + float(components["employer_pf"] or 0)
            + float(components["gratuity_provision"] or 0),
            2,
        ),
        "bonus": payroll.bonus or 0,
        "deduction": payroll.deduction or 0,
        "comments": payroll.comments or "",
        "final_salary": payroll.final_salary,
    }


def build_payroll_rows(month, year, save_calculated=False):
    payrun = get_payrun(month, year)
    payroll_approved = payrun.approved if payrun else False
    employees = Employee.query.filter(Employee.status == "Active").all()

    if payroll_approved:
        rows = []
        for employee in employees:
            payroll = get_adjustment_record(employee.id, month, year)
            if payroll:
                rows.append(serialize_saved_payroll(employee, payroll, month, year))
        return rows, True

    total_working_days = get_total_working_days(year, month)
    rows = []
    for employee in employees:
        row = calculate_employee_payroll(employee, month, year, total_working_days)
        if row:
            rows.append(row)

    if save_calculated:
        db.session.commit()

    return rows, False


def parse_month_year_from_request():
    pay_month = request.values.get("pay_month")
    if pay_month:
        year, month = map(int, pay_month.split("-"))
        return month, year

    month = request.values.get("month")
    year = request.values.get("year")
    if month and year:
        return int(month), int(year)

    return None, None


@admin_payroll_bp.route("/", methods=["GET"])
def payroll_dashboard():
    month, year = parse_month_year_from_request()
    payroll_data = None
    payroll_approved = False

    if month and year:
        payroll_data, payroll_approved = build_payroll_rows(month, year, save_calculated=False)

    return render_template(
        "admin/payroll.html",
        payroll_data=payroll_data,
        payroll_approved=payroll_approved,
        selected_month=month,
        selected_year=year,
    )


@admin_payroll_bp.route("/generate", methods=["POST"])
def generate_payrun():
    month, year = parse_month_year_from_request()
    if not month or not year:
        flash("Please select payroll month.", "danger")
        return redirect(url_for("admin_payroll.payroll_dashboard"))

    payroll_data, payroll_approved = build_payroll_rows(month, year, save_calculated=True)
    if payroll_approved:
        flash("Payroll already approved for the selected month.", "info")

    return render_template(
        "admin/payroll.html",
        payroll_data=payroll_data,
        payroll_approved=payroll_approved,
        selected_month=month,
        selected_year=year,
    )


@admin_payroll_bp.route("/approve", methods=["POST"])
def approve_payrun():
    month, year = parse_month_year_from_request()
    if not month or not year:
        flash("Payroll month is required.", "danger")
        return redirect(url_for("admin_payroll.payroll_dashboard"))

    payrun = get_payrun(month, year)
    if not payrun:
        payrun = PayrollRun(month=month, year=year, approved=True, approved_at=datetime.utcnow())
        db.session.add(payrun)
    else:
        payrun.approved = True
        payrun.approved_at = datetime.utcnow()

    record_loan_repayments_for_month(month, year)
    db.session.commit()
    flash("Payroll approved!", "success")
    return redirect(url_for("admin_payroll.payroll_dashboard", pay_month=f"{year}-{month:02d}"))


@admin_payroll_bp.route("/update-adjustments", methods=["POST"])
def update_adjustments():
    month, year = parse_month_year_from_request()
    if not month or not year:
        return "Payroll month is required.", 400

    payrun = get_payrun(month, year)
    if payrun and payrun.approved:
        return "Payroll locked!", 403

    employees = Employee.query.filter(Employee.status == "Active").all()
    for employee in employees:
        payroll = get_adjustment_record(employee.id, month, year)
        if not payroll:
            continue

        payroll.bonus = float(request.form.get(f"bonus_{employee.emp_code}") or 0)
        payroll.deduction = float(request.form.get(f"deduction_{employee.emp_code}") or 0)
        payroll.comments = request.form.get(f"comments_{employee.emp_code}") or ""
        payroll.final_salary = round(payroll.net_salary + payroll.bonus - payroll.deduction, 2)

    db.session.commit()
    return "", 200


@admin_payroll_bp.route("/get-data", methods=["GET", "POST"])
def get_payroll_data():
    month, year = parse_month_year_from_request()
    if not month or not year:
        return jsonify({"approved": False, "data": []}), 400

    payroll_data, payroll_approved = build_payroll_rows(month, year, save_calculated=False)
    return jsonify({"approved": payroll_approved, "data": payroll_data})


@admin_payroll_bp.route("/check-status", methods=["GET"])
def check_status():
    month, year = parse_month_year_from_request()
    if not month or not year:
        return jsonify({"approved": False}), 400

    payrun = get_payrun(month, year)
    return jsonify({"approved": payrun.approved if payrun else False})
