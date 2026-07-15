"""作品来源追踪 — 源 URL 的去重检测和状态标记。"""
from src.core.database import get_db


def source_set() -> set[str]:
    db = get_db()
    rows = db.execute("SELECT DISTINCT source FROM works").fetchall()
    return {r[0] for r in rows if r[0]}


def is_source_imported(url: str) -> bool:
    if not url:
        return False
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM works WHERE source = ? LIMIT 1", (url.strip(),)
    ).fetchone()
    return row is not None


def mark_deleted(source_urls: set[str]) -> int:
    db = get_db()
    with db:
        placeholders = ",".join("?" for _ in source_urls)
        cur = db.execute(
            f"UPDATE works SET source_status = 'deleted' WHERE source IN ({placeholders})",
            list(source_urls),
        )
        return cur.rowcount
