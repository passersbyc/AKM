"""一次性数据迁移脚本：CSV/JSON → SQLite

运行方式：
    python -m src.core.migrate_to_db
    或
    python src/core/migrate_to_db.py

迁移完成后的旧文件会被重命名为 .bak 备份。
"""

import csv
import json
import re
import shutil
import sys
import time
from pathlib import Path

from src.core.config import get_project_root, get_data_dir
from src.core.logging import logger
from src.core.database import get_db, init_db, _to_base36, next_counter
from src.core.registry import _get_author_id, _get_series_id


def _read_old_authors() -> list[dict]:
    p = get_data_dir() / "authors.csv"
    if not p.exists():
        return []
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_old_manifest() -> list[dict]:
    root = get_project_root()
    candidates = [
        root / "data" / "library_manifest.csv",
        root / "library_manifest.csv",
    ]
    for p in candidates:
        if p.exists():
            rows = []
            with open(p, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    if row.get("ID", "").strip():
                        rows.append(row)
            if rows:
                return rows
    return []


def _read_old_downloads() -> list[dict]:
    p = get_data_dir() / "download.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("works", [])
    except Exception:
        return []


def _read_old_id_registry() -> dict:
    p = get_data_dir() / ".id_registry.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_old_likes() -> dict:
    root = get_project_root()
    for name in ["pixiv_likes_data.json"]:
        p = root / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _read_old_blacklist() -> list:
    root = get_project_root()
    for name in ["pixiv_blacklist.json"]:
        p = root / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except Exception:
                pass
    return []


def migrate() -> int:
    init_db()
    db = get_db()

    existing_works = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    existing_authors = db.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    if existing_works > 0 or existing_authors > 0:
        logger.warning(f"数据库已有数据: {existing_authors} 位作者, {existing_works} 部作品")
        logger.warning("迁移将在该数据基础上追加。如需全新迁移请删除 library.db 后重试。")

    # ── 1. 迁移作者 ──
    logger.info("─ 迁移作者 …")
    old_authors = _read_old_authors()
    migrated_authors = 0
    skipped_authors = 0

    for row in old_authors:
        name = row.get("名称", "").strip()
        uid = row.get("Pixiv UID", "").strip()
        if not name and not uid:
            continue

        if uid:
            existing = db.execute(
                "SELECT author_id FROM pixiv_trackings WHERE pixiv_uid = ?", (uid,)
            ).fetchone()
        if not existing and name:
            existing = db.execute(
                "SELECT id FROM authors WHERE name = ?", (name,)
            ).fetchone()

        if existing:
            skipped_authors += 1
            continue

        local_id = row.get("本地ID", "").strip()
        if not local_id:
            seq = db.execute("SELECT COALESCE(MAX(CAST(id AS INTEGER)), 0) FROM authors WHERE id GLOB '[0-9]*'").fetchone()[0] + 1
            local_id = _to_base36(seq, 3)

        is_pixiv = uid and uid != "local"
        source = "pixiv" if is_pixiv else "local"

        db.execute(
            """INSERT OR REPLACE INTO authors
               (id, name, aliases, source, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                local_id, name,
                row.get("曾用名", "").strip(), source,
                row.get("备注", "").strip(),
                time.strftime("%Y-%m-%d %H:%M:%S"),
                time.strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

        if is_pixiv:
            old_status = row.get("状态", "active").strip()
            follow_status = "active" if old_status == "active" else "paused"
            db.execute(
                """INSERT OR REPLACE INTO pixiv_trackings
                   (author_id, pixiv_uid, homepage, follow_status,
                    latest_work_id, last_checked, note, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    local_id, uid,
                    row.get("主页", "").strip(),
                    follow_status,
                    row.get("最新作品", "").strip(),
                    row.get("上次检查", "").strip(),
                    row.get("备注", "").strip(),
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )

        migrated_authors += 1

    logger.info(f"  已迁移 {migrated_authors} 位作者" + (f"（跳过 {skipped_authors}）" if skipped_authors else ""))

    # ── 2. 迁移 ID 计数器 ──
    logger.info("─ 迁移 ID 计数器 …")
    old_reg = _read_old_id_registry()
    counter_count = 0

    seq = old_reg.get("_author_seq", 0)
    max_author_id = 0
    for r in db.execute("SELECT id FROM authors WHERE id != '000'").fetchall():
        try:
            val = int(r[0], 36)
            if val > max_author_id:
                max_author_id = val
        except ValueError:
            pass
    seq = max(seq, max_author_id)
    db.execute(
        "INSERT OR REPLACE INTO id_counters (name, value) VALUES ('author_seq', ?)",
        (seq,),
    )
    counter_count += 1

    for author_name, seq in old_reg.get("authors", {}).items():
        author_id = db.execute(
            "SELECT id FROM authors WHERE name = ?", (author_name,)
        ).fetchone()
        if not author_id:
            continue
        author_id = author_id[0]

        max_sid = 0
        for r in db.execute("SELECT id FROM series WHERE author_id = ?", (author_id,)).fetchall():
            try:
                val = int(r[0], 36) if r[0] else 0
                if val > max_sid:
                    max_sid = val
            except ValueError:
                pass

        for series_name, sid in old_reg.get("series", {}).get(author_name, {}).items():
            max_sid = max(max_sid, int(sid) if sid.isdigit() else int(sid, 36))
            existing_s = db.execute(
                "SELECT id FROM series WHERE author_id = ? AND name = ?",
                (author_id, series_name),
            ).fetchone()
            if not existing_s:
                db.execute(
                    "INSERT INTO series (id, author_id, name) VALUES (?, ?, ?)",
                    (_to_base36(int(sid) if sid.isdigit() else int(sid, 36), 2), author_id, series_name),
                )

        if max_sid > 0:
            db.execute(
                "INSERT OR REPLACE INTO id_counters (name, value) VALUES (?, ?)",
                (f"series:{author_id}", max_sid),
            )
            counter_count += 1

    for key, val in old_reg.get("work_counters", {}).items():
        parts = key.split("||")
        if len(parts) >= 3:
            file_type = parts[0]
            author_name = parts[1]
            series_name = parts[2] if len(parts) > 2 else ""
            type_char = {"小说": "n", "漫画": "c", "音乐": "m", "电影": "f", "美图集": "i"}.get(file_type, "0")
            author_id = db.execute(
                "SELECT id FROM authors WHERE name = ?", (author_name,)
            ).fetchone()
            if author_id:
                author_id = author_id[0]
                series_id = ""
                if series_name:
                    sr = db.execute(
                        "SELECT id FROM series WHERE author_id = ? AND name = ?",
                        (author_id, series_name),
                    ).fetchone()
                    if sr:
                        series_id = sr[0]
                db.execute(
                    "INSERT OR REPLACE INTO id_counters (name, value) VALUES (?, ?)",
                    (f"work:{type_char}:{author_id}:{series_id}", val),
                )
                counter_count += 1

    logger.info(f"  已迁移 {counter_count} 个计数器")

    # ── 3. 迁移作品 ──
    logger.info("─ 迁移作品 …")
    old_books = _read_old_manifest()
    migrated_books = 0
    skipped_books = 0

    for row in old_books:
        book_id = row.get("ID", "").strip()
        if not book_id:
            continue

        existing = db.execute("SELECT id FROM works WHERE id = ?", (book_id,)).fetchone()
        if existing:
            skipped_books += 1
            continue

        author_name = row.get("作者", "").strip() or "佚名"
        series_name = row.get("系列", "").strip()

        author_id = _get_author_id(author_name)
        series_id = ""
        if series_name:
            srow = db.execute(
                "SELECT id FROM series WHERE author_id = ? AND name = ?",
                (author_id, series_name),
            ).fetchone()
            if srow:
                series_id = srow[0]
            else:
                series_id = _get_series_id(author_name, series_name)

        favorite_val = 1 if row.get("收藏", "否") == "是" else 0
        try:
            rating_val = float(row.get("评分", 0) or 0)
        except (ValueError, TypeError):
            rating_val = 0
        try:
            likes_val = int(row.get("点赞", 0) or 0)
        except (ValueError, TypeError):
            likes_val = 0
        try:
            file_size = float(row.get("文件大小(KB)", 0) or 0)
        except (ValueError, TypeError):
            file_size = 0

        db.execute(
            """INSERT INTO works (id, title, author_id, series_id, tags, source,
               source_status, file_ext, file_type, imported_at, file_size_kb,
               md5, file_path, favorite, rating, description, likes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                book_id,
                row.get("标题", ""),
                author_id,
                series_id,
                row.get("标签", ""),
                row.get("来源", ""),
                row.get("源状态", "ok"),
                row.get("后缀", ""),
                row.get("分类", ""),
                row.get("导入时间", ""),
                file_size,
                row.get("MD5", ""),
                row.get("文件路径", ""),
                favorite_val,
                rating_val,
                row.get("简介", ""),
                likes_val,
            ),
        )
        migrated_books += 1

    logger.info(f"  已迁移 {migrated_books} 部作品" + (f"（跳过 {skipped_books}）" if skipped_books else ""))
    db.commit()

    # ── 4. 迁移下载队列 ──
    logger.info("─ 迁移下载队列 …")
    old_dl = _read_old_downloads()
    dl_count = 0
    for entry in old_dl:
        url = entry.get("url", "").strip()
        if not url:
            continue
        try:
            db.execute(
                "INSERT OR IGNORE INTO download_queue (url, status) VALUES (?, 'pending')",
                (url,),
            )
            dl_count += 1
        except Exception:
            pass
    logger.info(f"  已迁移 {dl_count} 条下载记录")

    # ── 5. 迁移 Pixiv 点赞数据 ──
    logger.info("─ 迁移 Pixiv 点赞数据 …")
    old_likes = _read_old_likes()
    likes_count = 0
    for work_id, info in old_likes.items():
        if isinstance(info, dict):
            db.execute(
                """INSERT OR REPLACE INTO pixiv_likes (work_id, like_count, title, author, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    str(work_id),
                    info.get("like_count", 0),
                    info.get("title", ""),
                    info.get("author", ""),
                    info.get("updated_at", 0),
                ),
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO pixiv_likes (work_id, like_count) VALUES (?, ?)",
                (str(work_id), int(info) if info else 0),
            )
        likes_count += 1
    logger.info(f"  已迁移 {likes_count} 条点赞数据")

    # ── 6. 迁移黑名单 ──
    logger.info("─ 迁移 Pixiv 黑名单 …")
    old_bl = _read_old_blacklist()
    bl_count = 0
    for work_id in old_bl:
        db.execute(
            "INSERT OR IGNORE INTO pixiv_blacklist (work_id) VALUES (?)",
            (str(work_id),),
        )
        bl_count += 1
    logger.info(f"  已迁移 {bl_count} 条黑名单")

    # ── 7. 备份旧文件 ──
    logger.info("─ 备份旧文件 …")
    backup_patterns = [
        "authors.csv",
        "library_manifest.csv",
        "download.json",
        ".id_registry.json",
        "pixiv_likes_data.json",
        "pixiv_blacklist.json",
    ]
    backed_up = 0
    for pattern in backup_patterns:
        candidates = [
            get_data_dir() / pattern,
            get_project_root() / pattern,
        ]
        for p in candidates:
            if p.exists():
                bak = p.with_suffix(p.suffix + ".bak")
                try:
                    p.rename(bak)
                    backed_up += 1
                except OSError:
                    pass

    logger.info(f"  已备份 {backed_up} 个文件（.bak）")

    # ── 汇总 ──
    total_authors = db.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    total_works = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    total_dl = db.execute("SELECT COUNT(*) FROM download_queue").fetchone()[0]

    logger.info("")
    logger.info("═══ 迁移完成 ═══")
    logger.info(f"  作者:    {total_authors} 位")
    logger.info(f"  作品:    {total_works} 部")
    logger.info(f"  下载队列: {total_dl} 个")
    logger.info(f"  点赞数据: {likes_count} 条")
    logger.info(f"  黑名单:   {bl_count} 条")
    logger.info(f"  计数器:   {counter_count} 个")
    logger.info("")
    logger.info("旧文件已备份为 .bak，确认无误后可手动删除。")

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    sys.exit(migrate())
