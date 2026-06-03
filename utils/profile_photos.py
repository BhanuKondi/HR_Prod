from pathlib import Path

from flask import current_app, url_for
from werkzeug.utils import secure_filename

from models.models import User


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PROFILE_PHOTO_DIR = Path("uploads") / "profile_photos"


def _photo_directory() -> Path:
    directory = Path(current_app.static_folder) / PROFILE_PHOTO_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _allowed_extension(filename: str) -> str | None:
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return suffix
    return None


def get_profile_photo_url(user_id: int | None) -> str | None:
    if not user_id:
        return None

    user = User.query.get(user_id)
    if user and user.profile_photo_path:
        return url_for("static", filename=user.profile_photo_path)

    directory = _photo_directory()
    for ext in ALLOWED_EXTENSIONS:
        photo_path = directory / f"user_{user_id}{ext}"
        if photo_path.exists():
            return url_for("static", filename=f"{PROFILE_PHOTO_DIR.as_posix()}/{photo_path.name}")
    return None


def save_profile_photo(user_id: int | None, photo_file) -> str | None:
    if not user_id or not photo_file or not photo_file.filename:
        return None

    extension = _allowed_extension(secure_filename(photo_file.filename))
    if not extension:
        return None

    directory = _photo_directory()
    for existing in directory.glob(f"user_{user_id}.*"):
        if existing.is_file():
            existing.unlink()

    destination = directory / f"user_{user_id}{extension}"
    photo_file.save(destination)
    return f"{PROFILE_PHOTO_DIR.as_posix()}/{destination.name}"
