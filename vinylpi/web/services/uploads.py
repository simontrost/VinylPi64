from __future__ import annotations

import time
from pathlib import Path

from werkzeug.utils import secure_filename

from vinylpi.paths import ALLOWED_EXT, BASE_DIR, UPLOAD_DIR
from vinylpi.web.services.config import get_current_fallback_path, set_fallback_image_path


def _safe_upload_path(filename: str) -> Path | None:
    safe_name = secure_filename(filename or "")
    if not safe_name or safe_name != filename:
        return None

    candidate = (UPLOAD_DIR / safe_name).resolve()
    try:
        candidate.relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        return None
    return candidate


def list_fallback_images() -> list[dict]:
    current_path = get_current_fallback_path()
    files = []

    for path in sorted(UPLOAD_DIR.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
        if not path.is_file() or path.suffix.lower().lstrip(".") not in ALLOWED_EXT:
            continue
        relative_path = path.relative_to(BASE_DIR).as_posix()
        files.append(
            {
                "filename": path.name,
                "path": relative_path,
                "url": f"/uploads/{path.name}",
                "is_current": relative_path == current_path,
            }
        )
    return files


def delete_fallback_image(filename: str) -> bool:
    path = _safe_upload_path(filename)
    if path is None or not path.is_file():
        return False
    path.unlink()
    return True


def upload_fallback_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None, "empty filename"

    original_name = secure_filename(file_storage.filename)
    if "." not in original_name:
        return None, "invalid file type"

    extension = original_name.rsplit(".", 1)[-1].lower()
    if extension not in ALLOWED_EXT:
        return None, "invalid file type"

    filename = f"fallback_{int(time.time())}.{extension}"
    destination = UPLOAD_DIR / filename
    file_storage.save(destination)

    relative_path = destination.relative_to(BASE_DIR).as_posix()
    set_fallback_image_path(relative_path)
    return {"image_path": relative_path}, None
