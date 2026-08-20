"""作者管理模块 — authors + pixiv_trackings 表读写入口。"""
import csv as _csv
import re
import time
from pathlib import Path
from typing import Any

from src.core.logging import logger
from src.core.config import get_project_root
from src.core.database import get_db, init_db, next_author_id, dict_from_row, dicts_from_rows

_AUTHOR_JOIN = """
    SELECT a.*, p.pixiv_uid, p.homepage,
           p.follow_status AS tracking_status,
           p.latest_work_id, p.last_checked,
           p.note AS tracking_note
    FROM authors a
    LEFT JOIN pixiv_trackings p ON a.id = p.author_id
"""


def _init() -> None:
    init_db()


def _merge_row(row: dict) -> dict:
    return {
        "id": row.get("id", ""),
        "name": row.get("name", ""),
        "aliases": row.get("aliases", ""),
        "source": row.get("source", ""),
        "site": row.get("_site", ""),
        "pixiv_uid": row.get("pixiv_uid") or "",
        "homepage": row.get("homepage") or "",
        "follow_status": row.get("tracking_status") or "active",
        "latest_work_id": row.get("latest_work_id") or "",
        "last_checked": row.get("last_checked") or "",
        "note": row.get("tracking_note") or row.get("note", ""),
        "favorite": bool(row.get("favorite", 0)),
    }


def _query_author(sql: str, params: tuple = ()) -> list[dict]:
    """作者查询：site_ctx 内查当前站点（避免跨站点同名混淆），否则遍历站点库。

    每行附加 _site 字段，供展示层区分作者所属站点。
    """
    from src.core.database import get_current_site, get_site_db
    from src.core.site import SITES
    site = get_current_site()
    if site:
        rows = [dict(r) for r in get_site_db(site).execute(sql, params).fetchall()]
        for r in rows:
            r["_site"] = site
        return rows
    out: list[dict] = []
    for s in SITES:
        for r in get_site_db(s).execute(sql, params).fetchall():
            d = dict(r)
            d["_site"] = s
            out.append(d)
    return out


def list_all() -> list[dict]:
    rows = _query_author(_AUTHOR_JOIN + " ORDER BY a.id")
    return [_merge_row(r) for r in rows]


def compute_author_tags(author_id: str, site: str = "") -> list[str]:
    from src.core.database import get_site_db, query_all_sites
    if site:
        rows = get_site_db(site).execute(
            "SELECT tags FROM works WHERE author_id = ? AND tags != ''",
            (author_id,)).fetchall()
    else:
        rows = query_all_sites(
            "SELECT tags FROM works WHERE author_id = ? AND tags != ''", (author_id,))
    seen = set()
    for r in rows:
        for t in (r[0] or "").split(","):
            t = t.strip()
            if t:
                seen.add(t)
    return sorted(seen)


def compute_author_top_tags(author_id: str, top_n: int = 5) -> list[tuple[str, int]]:
    from collections import Counter
    from src.core.database import query_all_sites
    rows = query_all_sites(
        "SELECT tags FROM works WHERE author_id = ? AND tags != ''", (author_id,))
    counter: Counter = Counter()
    for r in rows:
        for t in (r[0] or "").split(","):
            t = t.strip()
            if t:
                counter[t] += 1
    return counter.most_common(top_n)


def set_author_favorite(author_id: str, favorite: bool) -> bool:
    from src.core.database import get_current_site, get_site_db
    from src.core.site import SITES
    site = get_current_site()
    sites = [site] if site else SITES
    for s in sites:
        db = get_site_db(s)
        db.execute(
            "UPDATE authors SET favorite = ?, updated_at = datetime('now') WHERE id = ?",
            (1 if favorite else 0, author_id),
        )
        db.commit()
        if db.total_changes > 0:
            return True
    return False


def get_by_pixiv_uid(uid: str) -> dict | None:
    rows = _query_author(_AUTHOR_JOIN + " WHERE p.pixiv_uid = ?", (uid.strip(),))
    return _merge_row(rows[0]) if rows else None


def get_by_name(name: str) -> dict | None:
    rows = _query_author(_AUTHOR_JOIN + " WHERE a.name = ?", (name.strip(),))
    return _merge_row(rows[0]) if rows else None


def get_by_id(author_id: str) -> dict | None:
    rows = _query_author(_AUTHOR_JOIN + " WHERE a.id = ?", (author_id.strip(),))
    return _merge_row(rows[0]) if rows else None


def resolve(target: str) -> dict | None:
    target = target.strip()
    row = get_by_pixiv_uid(target)
    if row:
        return row
    row = get_by_id(target)
    if row:
        return row
    return get_by_name(target)


def upsert(uid: str = "", name: str = "", homepage: str = "",
           latest_work_id: str = "", note: str = "", **_: Any) -> dict | None:
    db = get_db()
    existing = None
    # pixiv_uid 是作者唯一身份，优先匹配（pixiv 作者重名很常见）。
    # 按名字兜底时：仅当命中行【没有 pixiv 身份】（本地导入作者升级为
    # pixiv 关注）才合并；命中行已有其他 pixiv_uid → 重名作者，必须分开。
    if uid and uid != "local":
        existing = get_by_pixiv_uid(uid)
    if not existing and name:
        found_by_name = get_by_name(name)
        if found_by_name and (not uid or not found_by_name.get("pixiv_uid")):
            existing = found_by_name

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    is_pixiv = bool(uid and uid != "local")

    if existing:
        author_id = existing["id"]
        aliases = existing.get("aliases", "") or ""
        if name and existing.get("name", "") and existing.get("name") != name:
            existing_aliases = [a.strip() for a in aliases.split(",") if a.strip()]
            if existing["name"] not in existing_aliases:
                existing_aliases.append(existing["name"])
            aliases = ",".join(existing_aliases)

        if name:
            db.execute(
                "UPDATE authors SET name = ?, aliases = ?, updated_at = ? WHERE id = ?",
                (name, aliases, now, author_id),
            )
        if is_pixiv:
            source = "pixiv"
            db.execute("UPDATE authors SET source = ? WHERE id = ?", (source, author_id))
            _upsert_tracking(db, author_id, uid, homepage, latest_work_id,
                             existing.get("last_checked", ""), note, now)
    else:
        author_id = next_author_id()
        while True:
            conflict = db.execute("SELECT 1 FROM authors WHERE id = ?", (author_id,)).fetchone()
            if not conflict:
                break
            author_id = next_author_id()

        source = "pixiv" if is_pixiv else "local"
        db.execute(
            "INSERT INTO authors (id, name, aliases, source, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (author_id, name or "", "", source, note, now, now),
        )
        if is_pixiv:
            _upsert_tracking(db, author_id, uid, homepage, latest_work_id, "", note, now)

    db.commit()
    return get_by_pixiv_uid(uid) or get_by_name(name)


def _upsert_tracking(db, author_id: str, uid: str, homepage: str,
                     latest_work_id: str, last_checked: str, note: str, now: str) -> None:
    existing = db.execute(
        "SELECT author_id FROM pixiv_trackings WHERE author_id = ?", (author_id,)
    ).fetchone()
    if existing:
        db.execute(
            """UPDATE pixiv_trackings SET homepage = ?, follow_status = 'active',
               latest_work_id = ?, note = ?, updated_at = ?
               WHERE author_id = ?""",
            (homepage, str(latest_work_id), note, now, author_id),
        )
    else:
        db.execute(
            """INSERT INTO pixiv_trackings
               (author_id, pixiv_uid, homepage,
                latest_work_id, last_checked, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (author_id, uid, homepage, str(latest_work_id),
             last_checked or now, note, now, now),
        )


def update(uid: str, **kwargs: Any) -> bool:
    db = get_db()
    field_map = {
        "pixiv_uid": "pixiv_uid", "homepage": "homepage",
        "follow_status": "follow_status",
        "latest_work_id": "latest_work_id", "最新作品": "latest_work_id",
        "last_checked": "last_checked", "上次检查": "last_checked",
        "note": "note", "备注": "note",
    }
    tracking_updates = {}
    for k, v in kwargs.items():
        field = field_map.get(k, k)
        if field == "follow_status":
            status = str(v) if v else ""
            if status in ("active", "paused", "dead"):
                tracking_updates["follow_status"] = status
            elif status == "deleted":
                tracking_updates["follow_status"] = "dead"
            else:
                tracking_updates["follow_status"] = "active"
        elif field in ("pixiv_uid", "homepage", "latest_work_id", "last_checked", "note"):
            tracking_updates[field] = str(v) if v is not None else ""

    if not tracking_updates:
        return False

    tracking_updates["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in tracking_updates)
    values = list(tracking_updates.values()) + [uid.strip()]
    with db:
        cur = db.execute(
            f"UPDATE pixiv_trackings SET {set_clause} WHERE pixiv_uid = ?", values
        )
        return cur.rowcount > 0


def unfollow(uid: str) -> bool:
    """取消关注 — 设置 follow_status='paused'。"""
    db = get_db()
    with db:
        cur = db.execute(
            "UPDATE pixiv_trackings SET follow_status = 'paused' WHERE pixiv_uid = ?",
            (uid.strip(),),
        )
        return cur.rowcount > 0


def delete_by_id(author_id: str) -> bool:
    """硬删除作者及所有关联数据（作品、系列、追踪记录）。"""
    if author_id == "000":
        return False
    db = get_db()
    # 删除关联作品文件
    rows = db.execute("SELECT file_path FROM works WHERE author_id = ?", (author_id,)).fetchall()
    for (fp,) in rows:
        if fp:
            try:
                from pathlib import Path
                p = Path(fp)
                if p.exists():
                    p.unlink()
            except Exception:
                pass
    # 删除关联作品的来源 URL（避免队列残留 stale 记录，pull 不再自动拉回）
    source_rows = db.execute(
        "SELECT source FROM works WHERE author_id = ? AND source != ''", (author_id,)
    ).fetchall()
    source_urls = [r[0] for r in source_rows]
    with db:
        db.execute("DELETE FROM works WHERE author_id = ?", (author_id,))
        db.execute("DELETE FROM series WHERE author_id = ?", (author_id,))
        db.execute("DELETE FROM pixiv_trackings WHERE author_id = ?", (author_id,))
        db.execute("DELETE FROM authors WHERE id = ?", (author_id,))
        if source_urls:
            placeholders = ",".join("?" for _ in source_urls)
            db.execute(
                f"DELETE FROM download_queue WHERE url IN ({placeholders})",
                source_urls,
            )
    return True


def register(name: str, uid: str = "", homepage: str = "") -> dict | None:
    if not name:
        return None
    source_uid = uid if uid and uid != "local" else ""
    return upsert(uid=source_uid, name=name, homepage=homepage)


def rename(local_id: str, new_name: str) -> int:
    db = get_db()
    with db:
        cur = db.execute(
            "UPDATE authors SET name = ?, updated_at = datetime('now') WHERE id = ?",
            (new_name, local_id),
        )
        return cur.rowcount


def migrate_follows_csv() -> int:
    root = get_project_root()
    for candidate in ["follows.csv", "follow.csv"]:
        p = root / candidate
        if not p.exists():
            continue
        count = 0
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            for row in _csv.DictReader(f):
                name = row.get("Author", row.get("作者", "")).strip()
                url = row.get("URL", row.get("主页", "")).strip()
                if not name and not url:
                    continue
                uid = ""
                if "pixiv.net/users/" in url:
                    m = re.search(r"/users/(\d+)", url)
                    if m:
                        uid = m.group(1)
                if not url and uid:
                    url = f"https://www.pixiv.net/users/{uid}"
                latest = row.get("Latest Work ID", row.get("最新作品", ""))
                upsert(uid=uid, name=name, homepage=url, latest_work_id=latest)
                count += 1
        if count > 0:
            import os
            bak = root / f"{candidate}.bak"
            p.rename(bak)
            logger.info(f"已迁移 {count} 条关注记录: {candidate} → authors")
        return count
    return 0


def get_local_id(name: str = "", uid: str = "") -> str:
    if uid:
        found = get_by_pixiv_uid(uid)
        if found:
            return found.get("id", "").strip()
    found = get_by_name(name)
    if found:
        return found.get("id", "").strip()
    return ""
