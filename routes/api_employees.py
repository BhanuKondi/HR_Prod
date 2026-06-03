import hmac
import os
import secrets

from flask import Blueprint, current_app, jsonify, request
from models.models import Employee, User
from models.db import db
from functools import wraps
from utils.authz import ROLE_USER, get_role_id

api_emp = Blueprint("api_emp", __name__, url_prefix="/api")

def get_api_credentials():
    username = os.getenv("HR_API_USERNAME", current_app.config.get("HR_API_USERNAME"))
    password = os.getenv("HR_API_PASSWORD", current_app.config.get("HR_API_PASSWORD"))
    return username, password


def basic_auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        expected_username, expected_password = get_api_credentials()

        if not auth:
            return jsonify({"error": "Authentication required"}), 401

        if not expected_username or not expected_password:
            return jsonify({"error": "API credentials are not configured"}), 503

        username_ok = hmac.compare_digest(auth.username or "", expected_username)
        password_ok = hmac.compare_digest(auth.password or "", expected_password)
        if not username_ok or not password_ok:
            return jsonify({"error": "Invalid credentials"}), 401

        return f(*args, **kwargs)

    return decorated


# =============================
#  SERIALIZER
# =============================

def serialize_employee(emp):
    return {
        "empCode": emp.emp_code,
        "firstName": emp.first_name,
        "lastName": emp.last_name,
        "email": emp.work_email,
        "phone": emp.phone,
        "department": emp.department,
        "jobTitle": emp.job_title,
        "address": emp.address,
        "dateOfJoining": str(emp.date_of_joining) if emp.date_of_joining else None,
        "status": emp.status,
        "managerEmpId": emp.manager_emp_id,
        "user": {
            "id": emp.user.id,
            "email": emp.user.email,
            "isActive": emp.user.is_active
        } if emp.user else None
    }


# =============================
#  1) GET ALL EMPLOYEES
# =============================

@api_emp.route("/employees", methods=["GET"])
@basic_auth_required
def api_get_all_employees():
    employees = Employee.query.all()
    data = [serialize_employee(e) for e in employees]

    return jsonify({
        "total": len(data),
        "data": data
    }), 200


# =============================
#  2) GET EMPLOYEE BY empCode
# =============================

@api_emp.route("/employee/<string:empCode>", methods=["GET"])
@basic_auth_required
def api_get_employee(empCode):
    emp = Employee.query.filter_by(emp_code=empCode).first()

    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    return jsonify(serialize_employee(emp)), 200


# =============================
#  3) CREATE EMPLOYEE
# =============================
# ======================================================
# CREATE EMPLOYEE (AUTO-GENERATE empCode)
# ======================================================
@api_emp.route("/employee", methods=["POST"])
@basic_auth_required
def api_create_employee():
    data = request.get_json(silent=True) or {}

    required_fields = [
        "firstName", "lastName", "email",
        "phone", "department", "jobTitle", "address",
        "dateOfJoining", "status", "managerEmpId"
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    # ================================================
    # AUTO-GENERATE EMP CODE (increment last one)
    # ================================================
    last_emp = Employee.query.order_by(Employee.emp_code.desc()).first()

    if last_emp:
        try:
            new_emp_code = str(int(last_emp.emp_code) + 1)
        except:
            return jsonify({"error": "Invalid empCode format in DB"}), 500
    else:
        new_emp_code = "1"  # First employee

    # Check email duplicate
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already exists"}), 400

    employee_role_id = get_role_id(ROLE_USER)
    if not employee_role_id:
        return jsonify({"error": "Employee role is not configured"}), 500

    temp_password = os.getenv("HR_API_DEFAULT_TEMP_PASSWORD") or f"Temp@{secrets.token_urlsafe(8)}"

    try:
        with db.session.begin():
            user = User(
                email=data["email"],
                display_name=f"{data['firstName']} {data['lastName']}",
                role_id=employee_role_id,
                is_active=True,
                must_change_password=True,
            )
            user.set_password(temp_password)
            db.session.add(user)
            db.session.flush()

            emp = Employee(
                emp_code=new_emp_code,
                first_name=data["firstName"],
                last_name=data["lastName"],
                work_email=data["email"],
                phone=data["phone"],
                address=data["address"],
                department=data["department"],
                job_title=data["jobTitle"],
                status=data["status"],
                date_of_joining=data["dateOfJoining"],
                manager_emp_id=data["managerEmpId"],
                user_id=user.id
            )
            db.session.add(emp)
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Failed to create employee: {exc}"}), 500

    return jsonify({
        "message": "Employee created successfully",
        "generatedEmpCode": new_emp_code,
        "employee": serialize_employee(emp),
        "temporaryPasswordSet": bool(os.getenv("HR_API_DEFAULT_TEMP_PASSWORD")),
    }), 201

# =============================
#  4) DELETE EMPLOYEE BY empCode
# =============================

@api_emp.route("/employee/<string:empCode>", methods=["DELETE"])
@basic_auth_required
def api_delete_employee(empCode):
    emp = Employee.query.filter_by(emp_code=empCode).first()

    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    # Delete associated user
    if emp.user:
        db.session.delete(emp.user)

    db.session.delete(emp)
    db.session.commit()

    return jsonify({"message": "Employee deleted successfully"}), 200
# =============================
#  5) ENABLE EMPLOYEE
# =============================
@api_emp.route("/employee/<string:empCode>/enable", methods=["PUT"])
@basic_auth_required
def api_enable_employee(empCode):
    emp = Employee.query.filter_by(emp_code=empCode).first()

    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    emp.status = "Active"

    if emp.user:
        emp.user.is_active = True

    db.session.commit()

    return jsonify({
        "message": "Employee enabled successfully",
        "employee": serialize_employee(emp)
    }), 200


# =============================
#  6) DISABLE EMPLOYEE
# =============================
@api_emp.route("/employee/<string:empCode>/disable", methods=["PUT"])
@basic_auth_required
def api_disable_employee(empCode):
    emp = Employee.query.filter_by(emp_code=empCode).first()

    if not emp:
        return jsonify({"error": "Employee not found"}), 404

    emp.status = "Inactive"

    if emp.user:
        emp.user.is_active = False

    db.session.commit()

    return jsonify({
        "message": "Employee disabled successfully",
        "employee": serialize_employee(emp)
    }), 200
