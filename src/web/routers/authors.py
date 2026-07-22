"""作者路由 — /authors 列表。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Query

from src.operations import list_authors_with_status
from src.web.app import templates

router = APIRouter()

PAGE_SIZE = 30


@router.get("/authors")
async def authors_list(
    request: Request,
    q: str = Query("", description="作者名搜索"),
    page: int = Query(1, ge=1),
):
    """作者列表。"""
    all_authors = list_authors_with_status()

    # 简单过滤
    if q:
        q_lower = q.lower()
        all_authors = [a for a in all_authors if q_lower in a.get("name", "").lower()]

    total = len(all_authors)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    items = all_authors[start:start + PAGE_SIZE]

    return templates.TemplateResponse(request, "authors.html", {
        "request": request,
        "active_page": "authors",
        "authors": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "q": q,
    })
