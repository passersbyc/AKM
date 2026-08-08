"""作者路由 — /authors 列表。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Query

from src.operations import list_authors_with_status, get_stats
from src.web.app import templates

router = APIRouter()

PAGE_SIZE = 24

# 状态筛选关键词映射
_STATUS_KW = {
    "active": ("活跃", "正常"),
    "paused": ("停更",),
    "dead": ("注销", "停止追更"),
}


@router.get("/authors")
def authors_list(
    request: Request,
    q: str = Query("", description="作者名/别名搜索"),
    status: str = Query("", description="状态筛选(active/paused/dead)"),
    page: int = Query(1, ge=1),
):
    """作者列表。"""
    all_authors = list_authors_with_status()

    # 过滤
    if q:
        q_lower = q.lower()
        all_authors = [
            a for a in all_authors
            if q_lower in a.get("name", "").lower()
            or q_lower in (a.get("aliases") or "").lower()
        ]
    if status in _STATUS_KW:
        kws = _STATUS_KW[status]
        all_authors = [
            a for a in all_authors
            if any(k in (a.get("status") or "") for k in kws)
        ]

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
        "status": status,
        "stats": get_stats(),
    })
