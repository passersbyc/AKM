"""stats 操作 - 库统计入口。"""
from collections import defaultdict

from src.core.work_manager import WorkManager


def get_stats() -> dict:
    stats = WorkManager.get_stats()
    rows = WorkManager.read()

    favorited_count = sum(1 for r in rows if r.get("收藏", "").strip() == "是")
    liked_count = sum(int(r.get("点赞", "0") or "0") for r in rows)
    ratings = []
    for r in rows:
        v = r.get("评分", "").strip()
        try:
            rv = float(v)
            if 0.0 <= rv <= 10.0:
                ratings.append(rv)
        except ValueError:
            pass

    id_type_count: dict[str, int] = defaultdict(int)
    for row in rows:
        book_id = row.get("ID", "")
        if len(book_id) >= 8:
            type_map = {"n": "小说", "c": "漫画", "m": "音乐", "f": "电影", "i": "美图集"}
            id_type_count[type_map.get(book_id[0], book_id[0])] += 1

    stats["favorited_count"] = favorited_count
    stats["liked_count"] = liked_count
    stats["rated_count"] = len(ratings)
    stats["id_type_distribution"] = dict(id_type_count)
    return stats


def aggregate(
    works: bool = False,
    authors: bool = False,
    series: bool = False,
    types: bool = False,
) -> dict:
    return WorkManager.aggregate(
        works=works, authors=authors, series=series, types=types,
    )


def get_recent_activity() -> dict:
    """返回最近活动三栏 {recent_open, recent_import, recent_download}，各限 5 条。"""
    from src.core.database import get_db
    db = get_db()
    recent_open = [dict(r) for r in db.execute(
        "SELECT work_id, title, opened_at FROM recent_opens ORDER BY opened_at DESC LIMIT 5"
    ).fetchall()]
    recent_import = [dict(r) for r in db.execute(
        "SELECT id, title, imported_at FROM works "
        "WHERE imported_at != '' AND (source = '' OR source = 'local' OR source = 'demo' OR source NOT LIKE 'http%') "
        "ORDER BY imported_at DESC LIMIT 5"
    ).fetchall()]
    recent_download = [dict(r) for r in db.execute(
        "SELECT id, title, imported_at, source FROM works "
        "WHERE imported_at != '' AND source LIKE 'http%' "
        "ORDER BY imported_at DESC LIMIT 5"
    ).fetchall()]
    return {"recent_open": recent_open, "recent_import": recent_import, "recent_download": recent_download}


def get_raw_tags() -> list[str]:
    """返回所有作品的 tags 字段列表（未拆分），供调用方归一化计数。"""
    from src.core.database import get_db
    db = get_db()
    rows = db.execute("SELECT tags FROM works WHERE tags != ''").fetchall()
    return [r["tags"] for r in rows]


def get_top_authors(limit: int = 5) -> list[dict]:
    """返回作品数 Top N 作者 [{name, cnt, fav_cnt}, ...]。"""
    from src.core.database import get_db
    db = get_db()
    rows = db.execute(
        "SELECT a.name, COUNT(w.id) as cnt, SUM(CASE WHEN w.favorite = 1 THEN 1 ELSE 0 END) as fav_cnt "
        "FROM authors a JOIN works w ON a.id = w.author_id "
        "GROUP BY a.id ORDER BY cnt DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_top_likes(limit: int = 5) -> list[dict]:
    """返回点赞排行 Top N [{work_id, title, author, like_count}, ...]。"""
    from src.core.database import get_db
    db = get_db()
    rows = db.execute(
        "SELECT pl.work_id, pl.title, pl.author, pl.like_count "
        "FROM pixiv_likes pl ORDER BY pl.like_count DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
