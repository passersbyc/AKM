"""仪表盘路由 — GET / 首页。"""
from __future__ import annotations

import math
import time
from datetime import datetime

from fastapi import APIRouter, Request
from src.core.database import short_id, get_db
from src.core.config import load_config

from src.operations import (
    get_stats,
    get_recent_activity,
    get_top_authors,
    get_top_likes,
    get_top_tags,
)
from src.operations.search_op import is_adult_row
from src.operations.recommend_op import get_recommendations
from src.web.app import templates

router = APIRouter()


def _kid_mode() -> bool:
    cfg = load_config().get("project_settings", {}) or {}
    return bool(cfg.get("kid_mode", False))


# 儿童模式下可见的统计（30s 缓存，避免每次首页渲染全表扫描）
_kid_stats_cache: dict = {"t": 0.0, "books": None, "favored": None}


def _kid_safe_counts() -> tuple[int, int]:
    """返回 (可见作品数, 可见收藏数)：仅统计标签不含 R-18 变体的作品。"""
    global _kid_stats_cache
    now = time.time()
    if _kid_stats_cache["books"] is not None and now - _kid_stats_cache["t"] < 30:
        return _kid_stats_cache["books"], _kid_stats_cache["favored"]
    db = get_db()
    books = favored = 0
    for r in db.execute("SELECT tags, favorite FROM works"):
        if not is_adult_row({"标签": r["tags"] or ""}):
            books += 1
            if r["favorite"]:
                favored += 1
    _kid_stats_cache = {"t": now, "books": books, "favored": favored}
    return books, favored


def _filter_adult(rows: list[dict], id_key: str) -> list[dict]:
    """儿童模式下过滤成人内容条目（id_key 为条目中的作品 ID 字段）。"""
    if not _kid_mode() or not rows:
        return rows
    ids = [r[id_key] for r in rows if r.get(id_key)]
    if not ids:
        return rows
    tag_map: dict[str, str] = {}
    db = get_db()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        placeholders = ",".join("?" * len(chunk))
        for r in db.execute(
            f"SELECT id, tags FROM works WHERE id IN ({placeholders})", chunk
        ):
            tag_map[r["id"]] = r["tags"] or ""
    return [r for r in rows if not is_adult_row({"标签": tag_map.get(r.get(id_key, ""), "")})]


def _time_ago(ts: str) -> str:
    """相对时间：刚刚 / N 分钟前 / N 小时前 / N 天前 / MM-DD。"""
    if not ts:
        return ""
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return (ts or "")[5:16]
    diff = (datetime.now() - dt).total_seconds()
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff // 3600)} 小时前"
    if diff < 86400 * 7:
        return f"{int(diff // 86400)} 天前"
    return dt.strftime("%m-%d")


def _fill_file_types(rows: list[dict], id_key: str) -> None:
    """批量给最近活动行补 file_type（用于类型色徽章）。"""
    ids = [r[id_key] for r in rows if r.get(id_key)]
    if not ids:
        return
    db = get_db()
    placeholders = ",".join("?" * len(ids))
    ft_rows = db.execute(
        f"SELECT id, file_type FROM works WHERE id IN ({placeholders})", ids
    ).fetchall()
    ft_map = {r["id"]: r["file_type"] for r in ft_rows}
    for r in rows:
        r["file_type"] = ft_map.get(r.get(id_key, ""), "")


@router.get("/")
def dashboard(request: Request):
    """仪表盘：统计概览 + 最近活动 + 猜你喜欢 + 标签/作者/点赞排行。"""
    stats = dict(get_stats())  # 拷贝：get_stats 返回 30s 缓存共享对象，直接改会污染缓存
    if _kid_mode():
        # 儿童模式下主数字改为「可见作品」口径（与列表/搜索一致）
        books, favored = _kid_safe_counts()
        stats["total_books"] = books
        stats["favorited_count"] = favored
    activity = get_recent_activity()
    top_authors = get_top_authors(limit=5)
    top_likes = get_top_likes(limit=5)
    top_tags = get_top_tags(limit=30)
    recommendations = get_recommendations(limit=24)

    # 大小人性化 + 分类分布（带百分比）
    size_kb = stats.get("total_size_kb", 0)
    if size_kb >= 1024 ** 2:
        size_human = f"{size_kb / 1024 ** 2:.2f} GB"
    elif size_kb >= 1024:
        size_human = f"{size_kb / 1024:.1f} MB"
    else:
        size_human = f"{size_kb:.0f} KB"
    stats["total_size_human"] = size_human

    type_dist = stats.get("type_distribution", {})
    total_type = sum(type_dist.values()) or 1
    type_share = [
        {"name": k, "count": v, "pct": round(v / total_type * 100, 1)}
        for k, v in sorted(type_dist.items(), key=lambda x: -x[1])
    ]

    # 词云：ECharts 渲染（椭圆 mask + 多色协调配色）。
    # 字号映射用线性 count（非 sqrt），拉开高频/低频落差——R-18(6148) vs 低频(个位数) 差距 30 倍，
    # 前端 sizeRange [13, 46] 保证最小 13px 可读、最大 46px 醒目
    top_tags = get_top_tags(limit=100)
    # 词云数据：
    # 1) 过滤过长标签（>6 字符）；
    # 2) value = count^0.62（幂映射）；
    # 3) 强头部放大系数：前 3 名 ×2.5、4-8 名 ×1.8、9-20 名 ×1.3，让前 1 名字号 ≈ 第 4 名 2×、前 1 名 ≈ 最小 3.6×，
    #    即使头部密集也能肉眼看出层次
    _filtered_tags = [(t, c) for t, c in top_tags if len(t) <= 6]
    word_cloud_data = [
        {
            "name": t,
            "value": round(
                pow(c, 0.62) * (
                    2.5 if i < 3 else
                    (1.8 if i < 8 else
                     (1.3 if i < 20 else 1.0))
                ),
                2,
            ),
            "count": c,
        }
        for i, (t, c) in enumerate(_filtered_tags)
    ]

    # 儿童模式：词云剔除 R-18 类标签
    if _kid_mode():
        word_cloud_data = [d for d in word_cloud_data if not is_adult_row({"标签": d["name"]})]

    # 给最近活动加 short_id + 相对时间 + 类型（横向封面流）
    activity["recent_open"] = _filter_adult(activity["recent_open"], "work_id")
    activity["recent_import"] = _filter_adult(activity["recent_import"], "id")
    activity["recent_download"] = _filter_adult(activity["recent_download"], "id")
    recommendations = _filter_adult(recommendations, "work_id")
    top_likes = _filter_adult(top_likes, "work_id")
    _fill_file_types(top_likes, "work_id")  # 用于排行榜封面 fallback 图标与类型色
    _fill_file_types(activity["recent_open"], "work_id")
    for row in activity["recent_open"]:
        row["short_id"] = short_id(row.get("work_id", ""))
        row["time_ago"] = _time_ago(row.get("opened_at", ""))
        row["time_str"] = (row.get("opened_at") or "")[5:16]
    _fill_file_types(activity["recent_import"], "id")
    _fill_file_types(activity["recent_download"], "id")
    for row in activity["recent_import"] + activity["recent_download"]:
        row["short_id"] = short_id(row.get("id", ""))
        row["time_ago"] = _time_ago(row.get("imported_at", ""))
        row["time_str"] = (row.get("imported_at") or "")[5:16]

    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "stats": stats,
        "activity": activity,
        "top_authors": top_authors,
        "top_likes": top_likes,
        "top_tags": top_tags,
        "word_cloud_data": word_cloud_data,
        "type_share": type_share,
        "recommendations": recommendations,
    })
