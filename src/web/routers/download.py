"""下载路由 — /download 下载队列管理。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Query

from src.operations import list_download_queue
from src.web.app import templates

router = APIRouter()

PAGE_SIZE = 30


@router.get("/download")
async def download_queue(
    request: Request,
    show_all: bool = Query(False, description="显示全部（含已下载/无效）"),
    page: int = Query(1, ge=1),
):
    """下载队列。"""
    all_items = list_download_queue(show_all=show_all)

    total = len(all_items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    items = all_items[start:start + PAGE_SIZE]

    # 统计
    stats = {
        "total": len(all_items),
        "pending": sum(1 for i in all_items if not i.get("is_in_db") and i.get("is_valid")),
        "downloaded": sum(1 for i in all_items if i.get("is_in_db")),
        "invalid": sum(1 for i in all_items if not i.get("is_valid")),
    }

    return templates.TemplateResponse(request, "download.html", {
        "request": request,
        "active_page": "download",
        "queue": items,
        "stats": stats,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "show_all": show_all,
    })
