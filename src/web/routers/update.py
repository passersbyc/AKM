"""更新路由 — /update 关注作者列表, /update/run 后台同步新作 + SSE 进度。"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from src.operations import source_op
from src.operations import get_stats
from src.web.app import templates

router = APIRouter()

# ── 全局同步状态（与下载页 pull 同模式） ─────────────────
_sync_lock = threading.Lock()
_sync_state: dict = {
    "running": False,
    "events": [],
    "seq": 0,
}


def _sync_callback(event: str, **kw):
    """同步进度回调 → 写入全局事件队列。"""
    with _sync_lock:
        _sync_state["seq"] += 1
        _sync_state["events"].append((_sync_state["seq"], {"event": event, **kw}))
        if len(_sync_state["events"]) > 500:
            _sync_state["events"] = _sync_state["events"][-500:]


def _run_sync_thread():
    """后台线程：检查关注作者新作并入队。"""
    try:
        candidates = source_op.resolve_sync_candidates(None)
        if not candidates:
            _sync_callback("error", message="(・ω・) 还没有关注任何作者呢～去「下载」页关注作者吧")
            return

        source_op.backfill_homepages(candidates)
        active = [r for r in candidates if r.get("follow_status", "") == "active"]
        paused = [r for r in candidates if r.get("follow_status", "") == "paused"]
        dead = [r for r in candidates if r.get("follow_status", "") == "dead"]
        now_ts = time.time()
        recheck_dead = [
            r for r in dead
            if source_op.should_recheck_dead(r.get("last_checked", ""), now_ts)
        ]

        targets = active + recheck_dead
        if not targets:
            _sync_callback("error", message="(◕‿◕) 关注作者都已是最新，暂不需要更新呢～")
            return

        first_url = next((r.get("homepage", "") for r in targets if r.get("homepage")), None)
        downloader = source_op.get_sync_downloader(first_url)
        if not downloader:
            _sync_callback("error", message="(｡•́︿•̀｡) 找不到已注册的下载器哦～")
            return

        max_workers = source_op.get_sync_max_workers(downloader)
        work_index, source_to_id = source_op.build_work_index(targets)

        _sync_callback("sync_start", total=len(targets), active=len(active), retry=len(recheck_dead))

        results: dict[str, dict] = {}
        download_lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for row in targets:
                uid = str(row.get("pixiv_uid", ""))
                futures[pool.submit(
                    source_op.sync_one_author, row, downloader, False,
                    work_index, source_to_id, None, download_lock,
                )] = (uid, str(row.get("name", "")))
            for future in as_completed(futures):
                uid, name = futures[future]
                try:
                    results[uid] = future.result()
                except Exception as e:
                    results[uid] = {"error": str(e)}
                _sync_callback("author_done", name=name, uid=uid,
                               **{k: results[uid].get(k, 0) for k in ("new", "deleted", "unchanged", "downloaded")})

        changed_ids = []
        changed_authors = []
        for row in targets:
            r = results.get(str(row.get("pixiv_uid", "")), {})
            if r.get("new") or r.get("deleted"):
                changed_authors.append({
                    "name": str(row.get("name", "")),
                    "uid": str(row.get("pixiv_uid", "")),
                    "new": r.get("new", 0),
                    "deleted": r.get("deleted", 0),
                    "downloaded": r.get("downloaded", 0),
                })
                changed_ids.append(str(row.get("pixiv_uid", "")))

        if changed_ids or source_op.has_new_favorites():
            source_op.save_updated_ids(targets, results)

        _sync_callback("sync_done",
                       changed=len(changed_authors),
                       changed_authors=changed_authors,
                       total=len(targets),
                       paused=len(paused),
                       dead=len(dead))
    except Exception as e:
        _sync_callback("error", message=str(e))
    finally:
        with _sync_lock:
            _sync_state["running"] = False


# ── 路由 ────────────────────────────────────────────────


@router.get("/update")
def update_page(request: Request):
    """关注更新页：作者列表 + 状态概览。"""
    candidates = source_op.resolve_sync_candidates(None)
    now_ts = time.time()

    groups = {"active": [], "paused": [], "dead": []}
    for row in candidates:
        status = row.get("follow_status", "")
        if status in groups:
            groups[status].append(row)

    # 需要检查 = 活跃 + 待重试的停更
    recheck_count = sum(
        1 for d in groups["dead"]
        if source_op.should_recheck_dead(d.get("last_checked", ""), now_ts)
    )
    pending = len(groups["active"]) + recheck_count

    return templates.TemplateResponse(request, "update.html", {
        "request": request,
        "active_page": "update",
        "groups": groups,
        "pending": pending,
        "total": len(candidates),
        "recheck_count": recheck_count,
        "last_checked": {},
        "sync_running": _sync_state["running"],
        "stats": get_stats(),
    })


@router.post("/update/run")
def update_run(request: Request):
    """触发后台同步，返回 SSE 流地址。"""
    with _sync_lock:
        if _sync_state["running"]:
            return {"status": "already_running"}
        _sync_state["running"] = True
        _sync_state["events"] = []
        _sync_state["seq"] = 0

    thread = threading.Thread(target=_run_sync_thread, daemon=True)
    thread.start()
    return {"status": "started"}


@router.get("/update/run/stream")
async def update_run_stream(request: Request):
    """SSE 流：实时推送同步进度。"""
    async def event_generator():
        last_seq = 0
        while True:
            with _sync_lock:
                new_events = [(s, e) for s, e in _sync_state["events"] if s > last_seq]
                running = _sync_state["running"]

            for seq, event in new_events:
                last_seq = seq
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            if not running and not new_events:
                await asyncio.sleep(2.0 if last_seq == 0 else 0.5)
                with _sync_lock:
                    more = any(s > last_seq for s, _ in _sync_state["events"])
                    running_now = _sync_state["running"]
                if not running_now and not more:
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
