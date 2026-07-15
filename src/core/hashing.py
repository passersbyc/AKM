import hashlib
from pathlib import Path

from src.core.config import get_project_root, load_config


def generate_file_md5(file_path: Path) -> str:
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def check_duplicate_by_md5(file_md5: str, manifest_name: str = None) -> tuple:
    if not file_md5:
        return False, ""
    from src.core.database import get_db, init_db
    init_db()
    db = get_db()
    row = db.execute("SELECT title FROM works WHERE md5 = ? LIMIT 1", (file_md5,)).fetchone()
    if row:
        return True, row[0]
    return False, ""
