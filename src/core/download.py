import sqlite3
from pathlib import Path

from src.core.config import get_data_dir
from src.core.database import get_db, init_db


def get_pending_urls() -> list[dict]:
    """返回待下载的 URL（有效、未入库、未拉黑）。"""
    init_db()
    db = get_db()
    rows = db.execute(
        "SELECT url, author_id, author_name, work_type, added_at "
        "FROM download_queue "
        "WHERE is_valid = 1 AND is_in_db = 0 AND is_blacklisted = 0"
    ).fetchall()
    return [{"url": r[0], "author_id": r[1] or "",
             "author_name": r[2] or "", "work_type": r[3] or "",
             "added_at": r[4]} for r in rows]


def read_download_json() -> dict:
    """兼容旧调用：返回待下载 URL。"""
    return {"works": get_pending_urls()}


def append_or_update(entries: list[dict]) -> int:
    """插入或更新队列。
    已存在且 is_in_db=1 → 跳过。
    已存在且 is_in_db=0 → 更新作者/类型，重置 valid/fail_count。
    不存在 → 插入。
    返回新增的待下载数量。
    """
    init_db()
    db = get_db()
    added = 0
    with db:
        for e in entries:
            url = e.get("url", "").strip()
            if not url:
                continue
            existing = db.execute(
                "SELECT is_in_db FROM download_queue WHERE url = ?", (url,)
            ).fetchone()
            if existing:
                if existing["is_in_db"]:
                    continue
                db.execute(
                    "UPDATE download_queue SET author_name=?, work_type=?, "
                    "is_valid=1, is_blacklisted=0, fail_count=0, "
                    "added_at=datetime('now') WHERE url=?",
                    (e.get("author_name", ""), e.get("work_type", ""), url))
            else:
                db.execute(
                    "INSERT INTO download_queue "
                    "(url, author_name, work_type, is_in_db) "
                    "VALUES (?, ?, ?, ?)",
                    (url, e.get("author_name", ""), e.get("work_type", ""),
                     e.get("is_in_db", 0)))
                added += 1
    return added


def append_to_download_json(entries: list[dict]) -> int:
    """兼容旧调用：委托给 append_or_update。"""
    return append_or_update(entries)


def _write_download_json(data: dict) -> None:
    """兼容旧调用。"""
    append_or_update(data.get("works", []))


def pop_download_json(urls: list[str]) -> list[dict]:
    db = get_db()
    popped = []
    with db:
        for url in urls:
            row = db.execute(
                "SELECT url, author_id, status, added_at "
                "FROM download_queue WHERE url = ?", (url,)
            ).fetchone()
            if row:
                popped.append({"url": row[0], "author_id": row[1] or "",
                               "status": row[2], "added_at": row[3]})
                db.execute("DELETE FROM download_queue WHERE url = ?", (url,))
    return popped


def mark_downloaded(url: str) -> None:
    get_db().execute(
        "UPDATE download_queue SET is_in_db=1, download_time=datetime('now'), "
        "fail_count=0 WHERE url=?", (url,))


def mark_invalid(url: str) -> None:
    """404/401/403：标记为无效。"""
    get_db().execute(
        "UPDATE download_queue SET is_valid=0 WHERE url=?", (url,))


def mark_failed(url: str) -> None:
    """失败次数 +1，满 3 次拉黑。"""
    db = get_db()
    db.execute(
        "UPDATE download_queue SET fail_count = fail_count + 1 WHERE url=?", (url,))
    row = db.execute(
        "SELECT fail_count FROM download_queue WHERE url=?", (url,)).fetchone()
    if row and row[0] >= 3:
        db.execute(
            "UPDATE download_queue SET is_blacklisted=1 WHERE url=?", (url,))


def mark_not_in_db(url: str) -> None:
    """setting check：文件缺失，触发重新下载。"""
    get_db().execute(
        "UPDATE download_queue SET is_in_db=0, fail_count=0 WHERE url=?", (url,))


def get_by_url(url: str) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM download_queue WHERE url = ?", (url,)).fetchone()
    if row:
        return dict(row)
    return None
