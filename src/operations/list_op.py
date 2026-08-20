"""列表操作 - 按资源类型分发。"""
from src.core.work_manager import WorkManager
from src.core.author_manager import list_all as _author_list
from src.core.series_manager import list_all as _series_list


def list_items(target_type: str, sort_by: str = "id", number: int = 0) -> dict:
    if target_type in ("book", "b"):
        items = WorkManager.read()
        if sort_by == "author":
            items.sort(key=lambda r: (r.get("ID", "")[1:4], r.get("ID", "")))
        elif sort_by == "id":
            items.sort(key=lambda r: (
                r.get("ID", "")[1:4],
                r.get("ID", "")[0],
                r.get("ID", "")[4:6],
                r.get("ID", "")[6:],
            ))
        elif sort_by == "title":
            items.sort(key=lambda r: r.get("标题", ""))
        elif sort_by == "series":
            items.sort(key=lambda r: (r.get("系列", ""), r.get("ID", "")))
        elif sort_by == "like":
            items.sort(key=lambda r: int(r.get("点赞", "0") or "0"), reverse=True)
        elif sort_by == "rating":
            items.sort(key=lambda r: float(r.get("评分", "0") or "0"), reverse=True)
        elif sort_by == "favorite":
            items.sort(key=lambda r: (r.get("收藏", "否") == "是", r.get("ID", "")), reverse=True)
        if number > 0:
            items = items[:number]
        return {"total": len(items), "items": items}

    if target_type in ("author", "a"):
        from collections import defaultdict
        from src.core.author_manager import compute_author_tags
        items = _author_list()
        all_works = WorkManager.read()
        author_info = defaultdict(lambda: {"works": 0, "series": set()})
        for w in all_works:
            a = w.get("作者", "")
            if not a:
                continue
            key = (w.get("站点", ""), a)
            author_info[key]["works"] += 1
            s = w.get("系列", "")
            if s:
                author_info[key]["series"].add(s)
        for item in items:
            name = item.get("name", "")
            key = (item.get("site", ""), name)
            info = author_info.get(key, {})
            item["work_count"] = info.get("works", 0)
            item["series_count"] = len(info.get("series", set()))
            item["tags"] = compute_author_tags(item["id"], item.get("site", ""))
        return {"total": len(items), "items": items}

    if target_type in ("series", "s"):
        items = _series_list()
        return {"total": len(items), "items": items}

    if target_type in ("type", "t"):
        agg = WorkManager.aggregate(types=True)
        type_items = agg.get("types", {})
        return {"total": len(type_items), "items": type_items}

    return {"total": 0, "items": []}


def list_recent_favorited(days: int = 7) -> list[dict]:
    """返回收藏作者最近 N 天内入库/发布的作品，按时间倒序。"""
    from datetime import datetime, timedelta
    from src.core.database import query_all_sites
    from src.core.queries import row_to_manifest

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    fav_authors = query_all_sites("SELECT id FROM authors WHERE favorite = 1")
    if not fav_authors:
        return []

    fav_ids = [r["id"] for r in fav_authors]
    placeholders = ",".join("?" * len(fav_ids))

    sql = f"""
        SELECT w.*, a.name AS _author_name, s.name AS _series_name
        FROM works w
        LEFT JOIN authors a ON w.author_id = a.id
        LEFT JOIN series s ON w.series_id = s.id AND s.author_id = w.author_id
        WHERE w.author_id IN ({placeholders})
        AND (
            w.imported_at >= ?
            OR (w.published_at != '' AND w.published_at >= ?)
        )
        ORDER BY COALESCE(NULLIF(w.published_at, ''), w.imported_at) DESC
    """
    rows = query_all_sites(sql, fav_ids + [cutoff, cutoff])
    return [row_to_manifest(dict(r)) for r in rows]


def list_authors_with_status() -> list[dict]:
    """返回作者列表，每项含 status 字段（活跃/停更/已死等）。"""
    from src.core.activity import build_author_stats, compute_status
    items = list_items("author")["items"]
    author_stats = build_author_stats()
    for row in items:
        lid = row.get("id", "")
        src = row.get("source", "local")
        tracking_status = row.get("follow_status", "")
        st = author_stats.get(lid) or author_stats.get(row.get("name", "")) or {}
        row["status"] = compute_status(lid, src, tracking_status,
                                       row.get("last_checked", ""),
                                       stats=st if st else None)
    return items


def list_download_queue(show_all: bool = False) -> list[dict]:
    """返回下载队列。show_all=True 含已下载/无效/拉黑，否则仅待下载（排除无效与黑名单）。"""
    from src.core.database import query_all_sites
    where = "" if show_all else "WHERE is_valid = 1 AND is_in_db = 0 AND is_blacklisted = 0 "
    rows = query_all_sites(
        "SELECT url, author_name, work_type, is_valid, is_in_db, "
        "is_blacklisted, fail_count, download_time, added_at "
        f"FROM download_queue {where}ORDER BY added_at DESC"
    )
    return [dict(r) for r in rows]


def get_download_stats() -> dict:
    """统计队列各状态数量（跨站点聚合）。"""
    from src.core.site import SITES
    from src.core.database import get_site_db
    agg = {"total": 0, "pending": 0, "downloaded": 0, "invalid": 0, "blacklisted": 0}
    for site in SITES:
        db = get_site_db(site)
        row = db.execute(
            "SELECT "
            "COUNT(*) as total, "
            "SUM(CASE WHEN is_valid=1 AND is_in_db=0 AND is_blacklisted=0 THEN 1 ELSE 0 END) as pending, "
            "SUM(CASE WHEN is_in_db=1 THEN 1 ELSE 0 END) as downloaded, "
            "SUM(CASE WHEN is_valid=0 AND is_in_db=0 THEN 1 ELSE 0 END) as invalid, "
            "SUM(CASE WHEN is_blacklisted=1 THEN 1 ELSE 0 END) as blacklisted "
            "FROM download_queue"
        ).fetchone()
        for k in agg:
            agg[k] += row[k] or 0
    return agg
