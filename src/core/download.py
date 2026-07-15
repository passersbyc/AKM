import sqlite3
from pathlib import Path

from src.core.config import get_data_dir
from src.core.database import get_db, init_db


def read_download_json() -> dict:
    init_db()
    db = get_db()
    rows = db.execute("SELECT url, author_id, status, added_at FROM download_queue").fetchall()
    works = [{"url": r[0], "author_id": r[1] or "", "status": r[2], "added_at": r[3]} for r in rows]
    return {"works": works}


def _write_download_json(data: dict) -> None:
    db = get_db()
    with db:
        db.execute("DELETE FROM download_queue")
        for entry in data.get("works", []):
            url = entry.get("url", "").strip()
            if url:
                try:
                    db.execute(
                        "INSERT INTO download_queue (url, status) VALUES (?, 'pending')",
                        (url,),
                    )
                except sqlite3.IntegrityError:
                    pass


def append_to_download_json(entries: list[dict]) -> int:
    init_db()
    db = get_db()
    added = 0
    with db:
        for entry in entries:
            url = entry.get("url", "").strip()
            if not url:
                continue
            try:
                db.execute(
                    "INSERT INTO download_queue (url, status) VALUES (?, 'pending')",
                    (url,),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass
    return added


def pop_download_json(urls: list[str]) -> list[dict]:
    db = get_db()
    popped = []
    with db:
        for url in urls:
            row = db.execute(
                "SELECT url, author_id, status, added_at FROM download_queue WHERE url = ?",
                (url,),
            ).fetchone()
            if row:
                popped.append({"url": row[0], "author_id": row[1] or "",
                               "status": row[2], "added_at": row[3]})
                db.execute("DELETE FROM download_queue WHERE url = ?", (url,))
    return popped
