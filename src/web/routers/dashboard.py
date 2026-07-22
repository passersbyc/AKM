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
async def dashboard(request: Request):
    """仪表盘：统计概览 + 最近活动 + 猜你喜欢 + 标签/作者/点赞排行。"""
    stats = get_stats()
    activity = get_recent_activity()
    top_authors = get_top_authors(limit=5)
    top_likes = get_top_likes(limit=5)
    top_tags = get_top_tags(limit=10)
    recommendations = get_recommendations(limit=8)

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
        "recommendations": recommendations,
    })
