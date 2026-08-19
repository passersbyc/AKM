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
    已存在且 is_in_db=1 且 works 表有记录 → 跳过。
    已存在且 is_in_db=1 但 works 表无记录 → 重置 is_in_db=0（文件已丢失，重新入队）。
    已存在且 is_in_db=0 → 更新作者/类型，重置 valid/fail_count。
    不存在 → 插入。
    返回新增/重置的待下载数量。
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
                    # 检查 works 表是否真有对应记录
                    work_row = db.execute(
                        "SELECT 1 FROM works WHERE source = ?", (url,)
                    ).fetchone()
                    if work_row:
                        continue  # 确实已下载，跳过
                    # works 表无记录但 is_in_db=1 → 文件已丢失，重置
                    db.execute(
                        "UPDATE download_queue SET is_in_db=0, is_valid=1, "
                        "is_blacklisted=0, fail_count=0, "
                        "author_name=?, work_type=?, "
                        "added_at=datetime('now') WHERE url=?",
                        (e.get("author_name", ""), e.get("work_type", ""), url))
                    added += 1
                else:
                    db.execute(
                        "UPDATE download_queue SET author_name=?, work_type=?, "
                        "is_valid=1, is_blacklisted=0, fail_count=0, "
                        "added_at=datetime('now') WHERE url=?",
                        (e.get("author_name", ""), e.get("work_type", ""), url))
            else:
                # 首次入队：调用方未显式指定入库状态时，查 works 表——
                # 已入库作品不再重复排队（避免 follow 漏判/重判导致重复下载）
                if "is_in_db" not in e:
                    work_row = db.execute(
                        "SELECT 1 FROM works WHERE source = ?", (url,)
                    ).fetchone()
                    if work_row:
                        continue
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
    """弹出并删除指定 URL 的队列记录（兼容旧调用）。"""
    db = get_db()
    popped = []
    with db:
        for url in urls:
            row = db.execute(
                "SELECT url, author_id, added_at "
                "FROM download_queue WHERE url = ?", (url,)
            ).fetchone()
            if row:
                popped.append({"url": row[0], "author_id": row[1] or "",
                               "added_at": row[2]})
                db.execute("DELETE FROM download_queue WHERE url = ?", (url,))
    return popped


def mark_downloaded(url: str) -> None:
    """标记为已下载，并从 works/authors 表回填 author_name（如果空）。"""
    db = get_db()
    with db:
        # 查 works 表 → authors 表获取作者名
        author_name = ""
        work_row = db.execute(
            "SELECT author_id FROM works WHERE source = ?", (url,)
        ).fetchone()
        if work_row and work_row[0]:
            name_row = db.execute(
                "SELECT name FROM authors WHERE id = ?", (work_row[0],)
            ).fetchone()
            if name_row and name_row[0]:
                author_name = name_row[0]

        if author_name:
            cur = db.execute(
                "UPDATE download_queue SET is_in_db=1, download_time=datetime('now'), "
                "fail_count=0, author_name=? WHERE url=?",
                (author_name, url))
        else:
            cur = db.execute(
                "UPDATE download_queue SET is_in_db=1, download_time=datetime('now'), "
                "fail_count=0 WHERE url=?", (url,))
        # 队列无该 URL（如 favorite 直下链路不经 download_queue）→ 补登记已下载，
        # 保证队列状态完整（verify/重下机制可感知）
        if cur.rowcount == 0:
            work_type = "novel" if "/novel/" in url else "illust"
            db.execute(
                "INSERT INTO download_queue "
                "(url, author_name, work_type, is_in_db, download_time) "
                "VALUES (?, ?, ?, 1, datetime('now'))",
                (url, author_name, work_type))


def mark_invalid(url: str) -> None:
    """404/401/403：标记为无效。"""
    db = get_db()
    with db:
        db.execute(
            "UPDATE download_queue SET is_valid=0 WHERE url=?", (url,))


def mark_failed(url: str) -> None:
    """失败次数 +1，满 3 次拉黑。"""
    db = get_db()
    with db:
        db.execute(
            "UPDATE download_queue SET fail_count = fail_count + 1 WHERE url=?", (url,))
        row = db.execute(
            "SELECT fail_count FROM download_queue WHERE url=?", (url,)).fetchone()
        if row and row[0] >= 3:
            db.execute(
                "UPDATE download_queue SET is_blacklisted=1 WHERE url=?", (url,))


def mark_not_in_db(url: str) -> None:
    """setting check：文件缺失，触发重新下载。"""
    db = get_db()
    with db:
        db.execute(
            "UPDATE download_queue SET is_in_db=0, fail_count=0 WHERE url=?", (url,))


def get_by_url(url: str) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM download_queue WHERE url = ?", (url,)).fetchone()
    if row:
        return dict(row)
    return None
