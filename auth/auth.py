import time
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, session, flash, url_for
from models.models import User
from models.db import db
from utils.authz import redirect_for_role
from utils.csrf import generate_csrf_token, validate_csrf_token

auth_bp = Blueprint("auth", __name__)

LOGIN_ATTEMPT_KEY = "_login_attempts"
LOGIN_LOCK_UNTIL_KEY = "_login_lock_until"
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 300

# ------------------------- LOGIN -------------------------
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    lock_until = session.get(LOGIN_LOCK_UNTIL_KEY)
    now = int(time.time())
    if lock_until and now < lock_until:
        remaining = lock_until - now
        minutes = max(1, (remaining + 59) // 60)
        flash(f"Too many failed login attempts. Try again in about {minutes} minute(s).", "danger")
        return render_template("login.html", csrf_token=generate_csrf_token())

    if lock_until and now >= lock_until:
        session.pop(LOGIN_LOCK_UNTIL_KEY, None)
        session.pop(LOGIN_ATTEMPT_KEY, None)

    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token")):
            flash("Your session expired. Please try signing in again.", "danger")
            return redirect(url_for('auth.login'))

        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        # User not found or wrong password
        if not user or not user.check_password(password):
            attempts = int(session.get(LOGIN_ATTEMPT_KEY, 0)) + 1
            session[LOGIN_ATTEMPT_KEY] = attempts
            if attempts >= MAX_LOGIN_ATTEMPTS:
                session[LOGIN_LOCK_UNTIL_KEY] = now + LOCKOUT_SECONDS
                flash("Too many failed login attempts. Please wait 5 minutes and try again.", "danger")
            else:
                remaining = MAX_LOGIN_ATTEMPTS - attempts
                flash(f"Invalid email or password. {remaining} attempt(s) remaining before temporary lock.", "danger")
            return redirect(url_for('auth.login'))

        # NEW: Check Terminated / Inactive
        if hasattr(user, "is_active") and not user.is_active:
            flash("Your account is disabled or terminated. Contact Admin.", "danger")
            return redirect(url_for('auth.login'))

        # Clear any previous session data before assigning the new identity.
        session.clear()
        session.permanent = True
        session['user_id'] = user.id
        session['email'] = user.email
        session['role_id'] = user.role_id
        session['role_name'] = user.role.name.lower().replace(" ", "_") if user.role and user.role.name else None
        user.last_login_at = datetime.utcnow()
        db.session.commit()

        # Force password change
        if user.must_change_password:
            flash("You must change your password before proceeding.", "warning")
            return redirect(url_for('settings.change_password'))

        # --------------------------
        #   ROLE-BASED REDIRECT
        # --------------------------
        role = user.role.name.lower()
        return redirect_for_role(role)

    return render_template("login.html", csrf_token=generate_csrf_token())


# ------------------------- LOGOUT -------------------------
@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
