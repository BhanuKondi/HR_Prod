import secrets

from flask import session


CSRF_SESSION_KEY = "_csrf_token"


def generate_csrf_token() -> str:
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf_token(submitted_token: str | None) -> bool:
    expected = session.get(CSRF_SESSION_KEY)
    return bool(expected and submitted_token and secrets.compare_digest(expected, submitted_token))
