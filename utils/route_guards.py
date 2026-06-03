from flask import flash, redirect, url_for


def require_employee_or_redirect(get_employee_fn, redirect_endpoint: str, message: str, category: str = "warning"):
    employee = get_employee_fn()
    if employee:
        return employee, None
    flash(message, category)
    return None, redirect(url_for(redirect_endpoint))


def require_owned_resource_or_redirect(
    resource,
    owner_id: int,
    resource_label: str,
    action_label: str,
    redirect_endpoint: str,
):
    if resource and getattr(resource, resource_label) == owner_id:
        return resource, None
    flash(f"You can {action_label} only your own requests.", "danger")
    return None, redirect(url_for(redirect_endpoint))


def require_assigned_resource_or_redirect(
    resource,
    assignee_id: int,
    assignee_field: str,
    message: str,
    redirect_endpoint: str,
):
    if resource and getattr(resource, assignee_field) == assignee_id:
        return resource, None
    flash(message, "danger")
    return None, redirect(url_for(redirect_endpoint))
