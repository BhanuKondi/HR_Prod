from flask import Blueprint, render_template, request, session, redirect, flash, url_for
from models.models import User
from models.db import db
from utils.authz import get_base_template_for_role, get_current_role, redirect_for_role
from utils.csrf import generate_csrf_token, validate_csrf_token

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")

@settings_bp.route("/change_password", methods=["GET", "POST"])
def change_password():
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    user = User.query.get(user_id)
    if not user:
        session.clear()
        flash("Your session is no longer valid. Please login again.", "warning")
        return redirect(url_for("auth.login"))

    role = get_current_role()
    base_template = get_base_template_for_role(role)

    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token")):
            flash("Your session expired. Please submit the form again.", "danger")
            return redirect(url_for("settings.change_password"))

        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        if not user.must_change_password:
            if not current_password or not user.check_password(current_password):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("settings.change_password"))

        if not new_password or len(new_password) < 8:
            flash("Password must be at least 8 characters.", "danger")
            return redirect(url_for("settings.change_password"))

        if new_password != confirm_password:
            flash("New password and confirm password must match.", "danger")
            return redirect(url_for("settings.change_password"))

        if current_password and current_password == new_password:
            flash("New password must be different from the current password.", "danger")
            return redirect(url_for("settings.change_password"))

        user.set_password(new_password)
        user.must_change_password = False
        db.session.commit()

        flash("Password updated successfully.", "success")

        # Redirect after success
        return redirect_for_role(role)

    return render_template(
        "change_password.html",
        user=user,
        base_template=base_template,
        csrf_token=generate_csrf_token(),
    )
