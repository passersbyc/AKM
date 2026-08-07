"""仪表盘路由 — GET / 首页。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from src.core.database import short_id

from src.operations import (
    get_stats,
    get_recent_activity,
    get_top_authors,
    get_top_likes,
    get_top_tags,
)
from src.operations.recommend_op import get_recommendations
from src.web.app import templates

router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    """仪表盘：统计概览 + 最近活动 + 猜你喜欢 + 标签/作者/点赞排行。"""
    stats = get_stats()
    activity = get_recent_activity()
    top_authors = get_top_authors(limit=5)
    top_likes = get_top_likes(limit=5)
    top_tags = get_top_tags(limit=30)
    recommendations = get_recommendations(limit=8)

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

    # 标签云：按数量分级字号与配色
    max_count = top_tags[0][1] if top_tags else 1
    cloud_colors = ["#5b4fc7", "#e8b458", "#e8a0bf", "#4fc79b", "#5b9bd5",
                    "#d55b8c", "#8b5bd5", "#d59b5b"]
    tag_cloud = [
        {"tag": t, "count": c,
         "size": max(1, min(5, round(c / max_count * 5))),
         "color": cloud_colors[i % len(cloud_colors)]}
        for i, (t, c) in enumerate(top_tags)
    ]

    # 给最近活动加 short_id
    for row in activity["recent_open"]:
        row["short_id"] = short_id(row.get("work_id", ""))
    for row in activity["recent_import"] + activity["recent_download"]:
        row["short_id"] = short_id(row.get("id", ""))

    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "stats": stats,
        "activity": activity,
        "top_authors": top_authors,
        "top_likes": top_likes,
        "top_tags": top_tags,
        "tag_cloud": tag_cloud,
        "type_share": type_share,
        "recommendations": recommendations,
    })
