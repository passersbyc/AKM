"""stats 操作 - 库统计入口。"""
import threading
import time
from collections import Counter, defaultdict

from src.core.work_manager import WorkManager

# ── get_stats 30 秒 TTL 缓存（侧边栏/仪表盘每页都调用，避免全库扫描） ──
_stats_cache: dict = {"t": 0.0, "data": None}
_stats_lock = threading.Lock()
_STATS_TTL = 30.0


def get_stats() -> dict:
    """全库统计（30s 缓存）。"""
    global _stats_cache
    now = time.time()
    with _stats_lock:
        if _stats_cache["data"] is not None and now - _stats_cache["t"] < _STATS_TTL:
            return _stats_cache["data"]

    stats = _compute_stats()

    with _stats_lock:
        _stats_cache = {"t": now, "data": stats}
    return stats


def invalidate_stats() -> None:
    """使统计缓存失效（导入/删除后调用）。"""
    global _stats_cache
    with _stats_lock:
        _stats_cache = {"t": 0.0, "data": None}


def _compute_stats() -> dict:
    """统计全库（无缓存，供内部/CLI 直接调用）。"""
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
    type_dist: Counter = Counter()
    source_dist: Counter = Counter()
    deleted_count = 0
    for row in rows:
        book_id = row.get("ID", "")
        if len(book_id) >= 8:
            type_map = {"n": "小说", "c": "漫画", "m": "音乐", "f": "电影", "i": "美图集"}
            id_type_count[type_map.get(book_id[0], book_id[0])] += 1
        ftype = row.get("分类", "")
        if ftype:
            type_dist[ftype] += 1
        src = row.get("来源", "") or ""
        source_dist["pixiv" if src.startswith("http") else (src or "local")] += 1
        if row.get("源状态", "ok") == "deleted":
            deleted_count += 1

    stats["favorited_count"] = favorited_count
    stats["liked_count"] = liked_count
    stats["rated_count"] = len(ratings)
    stats["avg_rating"] = round(sum(ratings) / len(ratings), 2) if ratings else 0.0
    stats["id_type_distribution"] = dict(id_type_count)
    stats["type_distribution"] = dict(type_dist.most_common())
    stats["source_distribution"] = dict(source_dist.most_common())
    stats["deleted_count"] = deleted_count

    # 库状态：关注分布 + 队列待下载
    from src.core.database import get_site_db
    from src.core.site import SITES
    follow_stats: dict[str, int] = defaultdict(int)
    # pixiv_trackings 在 pixiv 站点库
    for row in get_site_db("pixiv").execute(
        "SELECT follow_status, COUNT(*) as c FROM pixiv_trackings GROUP BY follow_status"
    ).fetchall():
        follow_stats[row["follow_status"]] = row["c"]
    queue_pending = 0
    for site in SITES:
        queue_pending += get_site_db(site).execute(
            "SELECT COUNT(*) FROM download_queue "
            "WHERE is_valid = 1 AND is_in_db = 0 AND is_blacklisted = 0"
        ).fetchone()[0]
    stats["follow_stats"] = dict(follow_stats)
    stats["queue_pending"] = queue_pending
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
    """返回最近活动三栏 {recent_open, recent_import, recent_download}，各限 8 条。

    recent_open 按 work_id 去重（同一作品被打开多次只保留最近一次），
    避免"最近打开"出现重复作品。
    """
    from src.core.database import get_meta_db, query_all_sites
    meta = get_meta_db()
    recent_open = [dict(r) for r in meta.execute(
        "SELECT site, work_id, title, MAX(opened_at) AS opened_at "
        "FROM recent_opens GROUP BY site, work_id ORDER BY opened_at DESC LIMIT 6"
    ).fetchall()]
    recent_import = sorted(
        [dict(r) for r in query_all_sites(
            "SELECT id, title, imported_at FROM works "
            "WHERE imported_at != '' AND (source = '' OR source = 'local' OR source = 'demo' OR source NOT LIKE 'http%')")],
        key=lambda r: r["imported_at"], reverse=True)[:6]
    recent_download = sorted(
        [dict(r) for r in query_all_sites(
            "SELECT id, title, imported_at, source FROM works "
            "WHERE imported_at != '' AND source LIKE 'http%'")],
        key=lambda r: r["imported_at"], reverse=True)[:6]
    return {"recent_open": recent_open, "recent_import": recent_import, "recent_download": recent_download}


def get_raw_tags() -> list[str]:
    """返回所有作品的 tags 字段列表（未拆分），供调用方归一化计数。"""
    from src.core.database import query_all_sites
    rows = query_all_sites("SELECT tags FROM works WHERE tags != ''")
    return [r["tags"] for r in rows]


def get_top_authors(limit: int = 5) -> list[dict]:
    """返回作品数 Top N 作者 [{name, cnt, fav_cnt}, ...]。"""
    from src.core.database import query_all_sites
    rows = query_all_sites(
        "SELECT a.name, COUNT(w.id) as cnt, SUM(CASE WHEN w.favorite = 1 THEN 1 ELSE 0 END) as fav_cnt "
        "FROM authors a JOIN works w ON a.id = w.author_id "
        "GROUP BY a.id")
    merged: dict[str, dict] = {}
    for r in rows:
        name = r["name"]
        d = merged.setdefault(name, {"name": name, "cnt": 0, "fav_cnt": 0})
        d["cnt"] += r["cnt"] or 0
        d["fav_cnt"] += r["fav_cnt"] or 0
    return sorted(merged.values(), key=lambda x: -x["cnt"])[:limit]


def get_top_likes(limit: int = 5) -> list[dict]:
    """返回点赞排行 Top N [{work_id, title, author, like_count}, ...]。"""
    from src.core.database import query_all_sites
    rows = query_all_sites(
        "SELECT w.id AS work_id, w.title, COALESCE(a.name, '') AS author, w.likes AS like_count "
        "FROM works w LEFT JOIN authors a ON w.author_id = a.id "
        "WHERE w.likes > 0")
    rows = sorted(rows, key=lambda r: -r["like_count"])[:limit]
    return [dict(r) for r in rows]


# ── 标签归一化（从 stats_cmd.py 下沉） ──

TAG_NORMALIZE: dict[str, str] = {
    "性転換": "性转",
    "性転換過程": "性转换过程",
    "記憶改変": "记忆改変",
    "現実改変": "现实改変",
    "精神変化": "精神变化",
    "他者変身": "他者变身",
    "強制変身": "强制变身",
    "口調強制": "口调强制",
    "人格変化": "人格变化",
    "人格改変": "人格改変",
    "立場逆転": "立场逆转",
    "立場変化": "立场变化",
    "他人変身": "他人变身",
    "認識改変": "认识改変",
    "存在改変": "存在改変",
    "常識改変": "常识改変",
    "人生改変": "人生改変",
    "肉体変化": "肉体变化",
    "転生": "转生",
    "中国语": "中国語",
}


def _normalize_tag(tag: str) -> str:
    """归一化标签：繁→简、大小写统一。"""
    t = TAG_NORMALIZE.get(tag, tag)
    if t.lower() == "tsf":
        return "TSF"
    return t


def get_top_tags(limit: int = 10) -> list[tuple[str, int]]:
    """返回归一化后的 Top N 标签及计数。"""
    all_tags = get_raw_tags()
    tag_counter: Counter = Counter()
    for tags_str in all_tags:
        for t in (tags_str or "").split(","):
            t = t.strip()
            if t:
                tag_counter[_normalize_tag(t)] += 1
    return tag_counter.most_common(limit)
