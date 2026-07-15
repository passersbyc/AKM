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
