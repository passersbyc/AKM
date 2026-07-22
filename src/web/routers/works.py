"""作品路由 — /works 列表+搜索, /works/{work_id} 详情。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Query
from src.core.database import short_id

from src.operations import search_works, get_info, get_related_works
from src.web.app import templates

router = APIRouter()

PAGE_SIZE = 24


@router.get("/works")
async def works_list(
    request: Request,
    q: str = Query("", description="标题关键词"),
    author: str = Query("", description="作者名"),
    tags: str = Query("", description="标签"),
    file_type: str = Query("", description="文件类型"),
    source: str = Query("", description="来源"),
    favorited: str = Query("", description="收藏"),
    page: int = Query(1, ge=1),
):
    """作品列表 + 多条件搜索。"""
    results = search_works(
        query=q, author=author, tags=tags,
        file_type=file_type, source=source,
        favorited=favorited,
    )

    # 分页
    total = len(results)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    items = results[start:start + PAGE_SIZE]

    # 加 short_id
    for item in items:
        item["short_id"] = short_id(item.get("id", ""))

    return templates.TemplateResponse(request, "works.html", {
        "request": request,
        "active_page": "works",
        "works": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "q": q,
        "author": author,
        "tags": tags,
        "file_type": file_type,
        "source": source,
        "favorited": favorited,
    })


@router.get("/works/{work_id}")
async def work_detail(request: Request, work_id: str):
    """作品详情页。"""
    info = get_info(work_id, "book")
    if not info:
        return templates.TemplateResponse(request, "work_detail.html", {
            "request": request,
            "active_page": "works",
            "work": None,
            "error": f"未找到作品 {work_id}",
        })

    info["short_id"] = short_id(info.get("id", ""))

    # 同系列相关作品
    related = []
    if info.get("series_id"):
        related = get_related_works(info["series_id"], exclude_id=info["id"])
        for r in related:
            r["short_id"] = short_id(r.get("id", ""))

    return templates.TemplateResponse(request, "work_detail.html", {
        "request": request,
        "active_page": "works",
        "work": info,
        "related": related,
    })
