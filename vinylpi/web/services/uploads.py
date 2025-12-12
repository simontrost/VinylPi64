import time
from pathlib import Path
from werkzeug.utils import secure_filename
from vinylpi.paths import UPLOAD_DIR, ALLOWED_EXT, BASE_DIR
from vinylpi.web.services.config import get_current_fallback_path, set_fallback_image_path

def list_fallback_images():
    current_path = get_current_fallback_path()
    files = []

    for p in sorted(UPLOAD_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        rel_path = str(p.relative_to(BASE_DIR))
        files.append({
            "filename": p.name,
            "path": rel_path,
            "url": f"/uploads/{p.name}",
            "is_current": (rel_path == current_path),
        })

    return files

def delete_fallback_image(filename: str) -> bool:
    p = UPLOAD_DIR / filename
    if not p.exists():
        return False
    p.unlink()
    return True

def upload_fallback_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None, "empty filename"

    ext = file_storage.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return None, "invalid file type"

    filename = secure_filename(f"fallback_{int(time.time())}.{ext}")
    dst_path = UPLOAD_DIR / filename
    file_storage.save(dst_path)

    rel_path = str(dst_path.relative_to(BASE_DIR))
    set_fallback_image_path(rel_path)
    return {"image_path": rel_path}, None
