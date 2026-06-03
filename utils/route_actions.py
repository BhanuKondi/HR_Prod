from collections.abc import Callable

from flask import flash

from models.db import db


def execute_db_action(
    mutator: Callable[[], None],
    success_message: str,
    after_commit: Callable[[], None] | None = None,
) -> bool:
    try:
        mutator()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return False

    if after_commit:
        try:
            after_commit()
        except Exception as exc:
            flash(f"Changes saved, but post-commit action failed: {exc}", "warning")

    flash(success_message, "success")
    return True
