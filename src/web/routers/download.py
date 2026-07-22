"""下载路由 — /download 下载队列管理 + URL 入队。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Query, Form

from src.operations import list_download_queue, queue_urls
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
        "message": "",
        "message_type": "",
    })


@router.post("/download/add")
async def download_add(
    request: Request,
    urls: str = Form(..., description="作品 URL，每行一个"),
):
    """批量入队作品 URL。"""
    url_list = [u.strip() for u in urls.strip().splitlines() if u.strip()]
    result = queue_urls(url_list)

    # 构建提示消息
    parts = []
    if result["queued"]:
        parts.append(f"新增 {result['queued']} 条")
    if result["skipped"]:
        parts.append(f"跳过 {result['skipped']} 条（已存在）")
    if result["invalid"]:
        parts.append(f"无效 {len(result['invalid'])} 条")
    message = "，".join(parts) if parts else "未识别到有效 URL"
    message_type = "success" if result["queued"] else "warning"

    # 重定向回下载页（带消息）
    all_items = list_download_queue(show_all=False)
    total = len(all_items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    items = all_items[:PAGE_SIZE]

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
        "page": 1,
        "total_pages": total_pages,
        "show_all": False,
        "message": message,
        "message_type": message_type,
    })
