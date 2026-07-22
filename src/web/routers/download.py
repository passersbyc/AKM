"""下载路由 — /download 队列管理 + URL 入队 + 关注作者 + SSE 下载进度。"""
from __future__ import annotations

import asyncio
import json
import threading

from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import StreamingResponse

from src.operations import list_download_queue, queue_urls, queue_author_works
from src.web.app import templates

router = APIRouter()

PAGE_SIZE = 30

# ── 全局下载状态 ──────────────────────────────────────────
_pull_lock = threading.Lock()
_pull_state: dict = {
    "running": False,
    "events": [],          # [(seq, event_dict)]
    "seq": 0,
    "result": None,        # 最终结果
}


def _pull_callback(event: str, **kw):
    """runner progress_callback → 写入全局事件队列。"""
    with _pull_lock:
        _pull_state["seq"] += 1
        _pull_state["events"].append((_pull_state["seq"], {
            "event": event, **kw,
        }))


def _run_pull_thread():
    """后台线程：执行下载并更新状态。"""
    global _pull_state
    try:
        from src.core.download import get_pending_urls
        from src.downloader.runner import run_download_groups

        pending = get_pending_urls()
        urls = [p["url"] for p in pending]
        if not urls:
            _pull_callback("error", message="下载队列为空")
            return

        _pull_callback("pull_start", total_urls=len(urls))

        results = run_download_groups(
            urls, mode="both",
            progress_callback=_pull_callback,
        )

        with _pull_lock:
            _pull_state["result"] = results
        _pull_callback("pull_done", results=results)
    except Exception as e:
        _pull_callback("error", message=str(e))
    finally:
        with _pull_lock:
            _pull_state["running"] = False


def _render_download_page(request: Request, *, message="", message_type="",
                          show_all=False, page=1):
    """渲染下载页（复用）。"""
    all_items = list_download_queue(show_all=show_all)
    total = len(all_items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    items = all_items[start:start + PAGE_SIZE]
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
        "message": message,
        "message_type": message_type,
        "pull_running": _pull_state["running"],
    })


# ── 路由 ──────────────────────────────────────────────────


@router.get("/download")
async def download_queue(
    request: Request,
    show_all: bool = Query(False),
    page: int = Query(1, ge=1),
):
    """下载队列页。"""
    return _render_download_page(request, show_all=show_all, page=page)


@router.post("/download/add")
async def download_add(
    request: Request,
    urls: str = Form(...),
):
    """批量入队作品 URL。"""
    url_list = [u.strip() for u in urls.strip().splitlines() if u.strip()]
    result = queue_urls(url_list)

    parts = []
    if result["queued"]:
        parts.append(f"新增 {result['queued']} 条")
    if result["skipped"]:
        parts.append(f"跳过 {result['skipped']} 条（已存在）")
    if result["invalid"]:
        parts.append(f"无效 {len(result['invalid'])} 条")
    message = "，".join(parts) if parts else "未识别到有效 URL"
    message_type = "success" if result["queued"] else "warning"

    return _render_download_page(request, message=message, message_type=message_type)


@router.post("/download/follow")
async def download_follow(
    request: Request,
    url: str = Form(...),
):
    """关注作者并将其全部作品入队。"""
    url = url.strip()
    if not url:
        return _render_download_page(request, message="请输入作者 URL", message_type="warning")

    result = queue_author_works(url)
    if not result:
        return _render_download_page(request, message=f"无法识别或访问: {url}", message_type="warning")

    parts = [f"已关注 {result['name']}"]
    if result.get("already_followed"):
        parts.append("（之前已关注）")
    if result.get("queued"):
        parts.append(f"，入队 {result['queued']} 个作品")
    elif result.get("total") == 0:
        parts.append("，无新作品")

    return _render_download_page(request, message="".join(parts), message_type="success")


@router.post("/download/pull")
async def download_pull(request: Request):
    """触发下载（后台线程），返回 SSE 流地址。"""
    with _pull_lock:
        if _pull_state["running"]:
            return {"status": "already_running"}
        _pull_state["running"] = True
        _pull_state["events"] = []
        _pull_state["seq"] = 0
        _pull_state["result"] = None

    thread = threading.Thread(target=_run_pull_thread, daemon=True)
    thread.start()
    return {"status": "started"}


@router.get("/download/pull/stream")
async def download_pull_stream(request: Request):
    """SSE 流：实时推送下载进度。"""
    async def event_generator():
        last_seq = 0
        while True:
            # 读取新事件
            with _pull_lock:
                new_events = [(s, e) for s, e in _pull_state["events"] if s > last_seq]
                running = _pull_state["running"]

            for seq, event in new_events:
                last_seq = seq
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # 下载结束且没有更多事件 → 关闭流
            if not running and not new_events:
                # 再等一拍确认没有新事件
                await asyncio.sleep(0.5)
                with _pull_lock:
                    more = any(s > last_seq for s, _ in _pull_state["events"])
                if not more:
                    yield f"data: {json.dumps({'event': 'stream_end'}, ensure_ascii=False)}\n\n"
                    break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
