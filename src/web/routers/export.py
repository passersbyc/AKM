"""导出路由 — 筛选结果异步导出 + 单作品导出 + 任务状态查询 + 打开导出目录。

从 works.py 拆分而来，职责单一：导出相关。异步导出任务表为内存态
（进程重启即失效，可接受），带 TTL 过期清理防止无限增长。
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from src.core.config import load_config
from src.web.deps import safe_search

router = APIRouter()

# ── 异步导出任务表（内存态 + TTL 过期清理）─────────────────
_EXPORT_TASKS: dict[str, dict] = {}
_EXPORT_LOCK = threading.Lock()
_EXPORT_TTL_SECONDS = 3600  # 任务状态保留 1 小时


def _prune_expired_locked() -> None:
    """清理过期任务（须在 _EXPORT_LOCK 内调用）。"""
    now = time.time()
    expired = [k for k, v in _EXPORT_TASKS.items()
               if now - v.get("created_at", 0) > _EXPORT_TTL_SECONDS]
    for k in expired:
        _EXPORT_TASKS.pop(k, None)


def _task_set(task_id: str, **fields) -> None:
    with _EXPORT_LOCK:
        task = _EXPORT_TASKS.setdefault(task_id, {})
        task.update(fields)
        task.setdefault("created_at", time.time())
        _prune_expired_locked()


def _task_get(task_id: str) -> dict:
    with _EXPORT_LOCK:
        task = _EXPORT_TASKS.get(task_id)
        if not task:
            return {}
        if time.time() - task.get("created_at", 0) > _EXPORT_TTL_SECONDS:
            _EXPORT_TASKS.pop(task_id, None)
            return {}
        return dict(task)


# ── 路由 ──────────────────────────────────────────────────


@router.post("/works/export")
async def export_works_filtered(
    q: str = Form(""),
    author: str = Form(""),
    tags: str = Form(""),
    file_type: str = Form(""),
    source: str = Form(""),
    favorited: str = Form(""),
    output_format: str = Form(""),
):
    """导出当前筛选结果（异步任务）：立即返回 task_id，前端轮询 /works/export/status/{id}。"""
    from src.export.models import ExportRequest

    rows = safe_search(query=q, author=author, tags=tags,
                       file_type=file_type, source=source, favorited=favorited)
    if not rows:
        return JSONResponse({"success": False, "error": "没有符合条件的作品可导出"}, status_code=400)

    cfg = load_config().get("project_settings", {}) or {}
    dest = str(cfg.get("export_path") or Path.cwd())
    fmt = output_format or cfg.get("export_format") or "folder"
    if fmt not in ("folder", "zip", "epub"):
        fmt = "folder"

    cond = [x for x in [q, author, tags, file_type, source] if x]
    if favorited == "yes":
        cond.append("已收藏")
    export_name = "-".join(cond) if cond else "全部作品"

    req = ExportRequest(query=export_name, dest_dir=Path(dest),
                        export_name=export_name, mode="author",
                        output_format=fmt, prefiltered=True)
    task_id = uuid.uuid4().hex[:12]
    _task_set(task_id, status="pending")

    def _worker():
        from src.export import export_works as run_export
        _task_set(task_id, status="running")
        try:
            result = run_export(rows, req)
            _task_set(task_id,
                      status="done" if result.success else "failed",
                      exported=result.exported_count,
                      destination=str(result.destination) if result.destination else "",
                      error=result.error)
        except Exception as exc:  # noqa: BLE001
            _task_set(task_id, status="failed", error=f"导出失败: {exc}")

    threading.Thread(target=_worker, daemon=True).start()
    return {"success": True, "task_id": task_id, "status": "pending"}


@router.get("/works/export/status/{task_id}")
def export_status(task_id: str):
    """查询异步导出任务状态。"""
    t = _task_get(task_id)
    if not t:
        return JSONResponse({"success": False, "error": "任务不存在"}, status_code=404)
    return {"success": True, "task_id": task_id, **t}


@router.post("/works/export/open")
def export_open(dest: str = Form("")):
    """在系统文件管理器中打开导出目录。"""
    if not dest or not os.path.isdir(dest):
        return JSONResponse({"success": False, "error": "目录不存在"}, status_code=400)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", dest])
        elif sys.platform == "win32":
            os.startfile(dest)
        else:
            subprocess.Popen(["xdg-open", dest])
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
    return {"success": True}


@router.post("/works/{work_id}/export")
def export_single_work(work_id: str):
    """导出单个作品到配置的导出目录。"""
    from src.operations.export_op import export_work

    cfg = load_config().get("project_settings", {}) or {}
    dest = str(cfg.get("export_path") or Path.cwd())
    fmt = cfg.get("export_format") or "folder"
    if fmt not in ("folder", "zip", "epub"):
        fmt = "folder"
    return export_work(work_id, Path(dest), output_format=fmt)
