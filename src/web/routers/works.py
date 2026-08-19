"""作品路由 — /works 列表+搜索, /works/{work_id} 详情, /works/{work_id}/cover 封面, /works/{work_id}/open 打开文件。"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Request, Query, Form
from fastapi.responses import Response, JSONResponse
from src.core.database import short_id
from src.core.config import load_config

from src.operations import search_works, get_info, get_related_works, get_stats
from src.web.app import templates
from src.web.cover import extract_cover

router = APIRouter()


def _kid_mode() -> bool:
    """儿童模式开关（读设置）。"""
    cfg = load_config().get("project_settings", {}) or {}
    return bool(cfg.get("kid_mode", False))


def _safe_search(**kw):
    """按当前儿童模式状态过滤的搜索。"""
    return search_works(**kw, safe_mode=_kid_mode())

PAGE_SIZE = 24
# 按作者分组视图：每组预览上限（大标签下避免渲染数千封面）
GROUP_PREVIEW = 12
# 首屏直接渲染卡片的分组数，其余分组折叠按需 AJAX 加载
LAZY_GROUPS = 3

# 异步导出任务表（内存态，进程重启即失效，可接受）
_EXPORT_TASKS: dict[str, dict] = {}
_EXPORT_LOCK = threading.Lock()


def _task_set(task_id: str, **fields) -> None:
    with _EXPORT_LOCK:
        _EXPORT_TASKS.setdefault(task_id, {}).update(fields)


def _task_get(task_id: str) -> dict:
    with _EXPORT_LOCK:
        return dict(_EXPORT_TASKS.get(task_id, {}))

# 中文 key → 英文 key 映射（operations 层返回中文，模板用英文）
_KEY_MAP = {
    "ID": "id",
    "标题": "title",
    "作者": "author_name",
    "系列": "series_name",
    "标签": "tags",
    "来源": "source",
    "源状态": "source_status",
    "后缀": "file_ext",
    "分类": "file_type",
    "导入时间": "imported_at",
    "文件大小(KB)": "file_size_kb",
    "MD5": "md5",
    "文件路径": "file_path",
    "收藏": "favorite",
    "评分": "rating",
    "简介": "description",
    "点赞": "likes",
}


def _normalize_work(raw: dict) -> dict:
    """将 operations 层的中文 key 映射为模板用的英文 key。"""
    w = {}
    for zh_key, en_key in _KEY_MAP.items():
        w[en_key] = raw.get(zh_key, "")
    # 类型转换
    try:
        w["file_size_kb"] = float(w["file_size_kb"]) if w["file_size_kb"] else 0
    except (ValueError, TypeError):
        w["file_size_kb"] = 0
    try:
        w["likes"] = int(w["likes"]) if w["likes"] else 0
    except (ValueError, TypeError):
        w["likes"] = 0
    w["favorite"] = w.get("favorite") in ("是", True, 1, "1")
    w["short_id"] = short_id(w.get("id", ""))
    # 文件大小人性化
    kb = w.get("file_size_kb") or 0
    if kb >= 1024 ** 2:
        w["size_human"] = f"{kb / 1024 ** 2:.1f} GB"
    elif kb >= 1024:
        w["size_human"] = f"{kb / 1024:.1f} MB"
    elif kb > 0:
        w["size_human"] = f"{kb:.0f} KB"
    else:
        w["size_human"] = ""
    return w


def _id_num(work_id: str) -> tuple:
    """提取作品 ID 尾部的章节序号。

    ID 结构：{类型}{作者3位base36}{系列2位base36}{话数4位base36}
    同系列内 ID 尾部 4 位按 base36 解析即为话数。
    """
    w = work_id or ""
    m = re.search(r"([0-9a-z]{4})$", w)
    if m:
        try:
            return (int(m.group(1), 36), w)
        except ValueError:
            pass
    return (0, w)


def _build_series_entry(raw_members: list[dict], global_count: int | None = None) -> dict:
    """将同系列的作品列表合并为一个系列卡片条目。

    系列封面统一使用第一章（ID 序号最小）的作品封面。
    series_count 默认显示"全库该系列总数"（与系列页 total 口径一致），
    避免跨作者同名系列时"列表卡 N 部 / 系列页 M 部"不一致。
    """
    members = [_normalize_work(m) for m in
               sorted(raw_members, key=lambda r: _id_num(r.get("ID", "")))]
    rep = members[0]
    e = dict(rep)
    e["kind"] = "series"
    e["cover_id"] = rep.get("id", "")  # 系列封面用第一章的作品 ID
    e["id"] = ""  # 系列无单作品 ID，不可本地打开
    e["series_name"] = rep.get("series_name", "")
    e["title"] = rep.get("series_name", "")
    e["series_count"] = global_count if global_count is not None else len(members)
    e["favorite"] = any(m["favorite"] for m in members)
    ratings = [float(m["rating"]) for m in members if m.get("rating")]
    e["rating"] = max(ratings) if ratings else ""
    authors = sorted({m["author_name"] for m in members if m.get("author_name")})
    e["author_name"] = ", ".join(authors[:2]) + (" 等" if len(authors) > 2 else "")
    return e


def _series_global_counts(names: list[str]) -> dict[str, int]:
    """一次查询所有系列名的全库作品数（与系列页 search(series=name) 口径一致）。"""
    from src.core.database import query_all_sites
    names = [n for n in dict.fromkeys(names) if n]
    if not names:
        return {}
    placeholders = ",".join("?" * len(names))
    rows = query_all_sites(
        f"SELECT s.name, COUNT(*) FROM works w "
        f"JOIN series s ON w.series_id = s.id AND s.author_id = w.author_id "
        f"WHERE s.name IN ({placeholders}) GROUP BY s.name",
        names,
    )
    result: dict[str, int] = {}
    for r in rows:
        result[r[0]] = result.get(r[0], 0) + r[1]
    return result


def _merge_series(results: list[dict]) -> list[dict]:
    """将搜索结果中的同系列作品合并为一个系列条目（保持首次出现顺序）。"""
    ordered: list[dict] = []
    series_index: dict[str, list] = {}
    for raw in results:
        sname = (raw.get("系列") or "").strip()
        if sname:
            if sname in series_index:
                series_index[sname].append(raw)
            else:
                series_index[sname] = [raw]
                ordered.append({"kind": "series", "_members": series_index[sname]})
        else:
            ordered.append({"kind": "work", "_work": raw})
    # 全库系列总数（与系列页口径一致），一次批量查询
    global_counts = _series_global_counts(list(series_index.keys()))
    return [
        _build_series_entry(item["_members"], global_counts.get(item["_members"][0].get("系列", "").strip(), None))
        if item["kind"] == "series"
        else _normalize_work(item["_work"])
        for item in ordered
    ]


def _group_extras(works: list[dict]) -> dict:
    """作者分组的辅助统计：系列数与类型分布（供分组头展示）。"""
    series_names = set()
    type_counts: dict[str, int] = {}
    for raw in works:
        sname = (raw.get("系列") or "").strip()
        if sname:
            series_names.add(sname)
        ftype = raw.get("分类") or "未知"
        type_counts[ftype] = type_counts.get(ftype, 0) + 1
    return {
        "series_count": len(series_names),
        "type_counts": type_counts,
    }


@router.get("/works")
def works_list(
    request: Request,
    q: str = Query("", description="标题关键词"),
    author: str = Query("", description="作者名"),
    tags: str = Query("", description="标签"),
    file_type: str = Query("", description="文件类型"),
    source: str = Query("", description="来源"),
    favorited: str = Query("", description="收藏"),
    page: int = Query(1, ge=1),
):
    """作品列表：默认按作者分组，组内同系列合并显示。"""
    results = _safe_search(
        query=q, author=author, tags=tags,
        file_type=file_type, source=source,
        favorited=favorited,
    )

    # 按作者聚合（保持首次出现顺序），组内同系列合并
    from collections import OrderedDict
    raw_groups: "OrderedDict[str, list]" = OrderedDict()
    for w in results:
        name = w.get("作者") or "佚名"
        raw_groups.setdefault(name, []).append(w)

    author_groups: "OrderedDict[str, dict]" = OrderedDict()
    ctx: dict = {
        "request": request,
        "active_page": "works",
        "group": "author",
        "works": [],
        "total": len(results),
        "stats": get_stats(),
        "q": q, "author": author, "tags": tags,
        "file_type": file_type, "source": source, "favorited": favorited,
        "export_fmt": (load_config().get("project_settings", {}) or {}).get("export_format", "folder"),
        "export_path": (load_config().get("project_settings", {}) or {}).get("export_path", ""),
    }

    if author and results:
        # 单作者筛选：该作者全部作品完整分页展示（不再截断）
        name = next(iter(raw_groups.keys()))
        merged = _merge_series(results)
        total_pages = max(1, (len(merged) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages)
        start = (page - 1) * PAGE_SIZE
        author_groups[name] = {
            "works": merged[start:start + PAGE_SIZE],
            "total": len(results),
            "pages": total_pages,
            "page": page,
            **_group_extras(results),
        }
        ctx.update(page=page, total_pages=total_pages)
    else:
        # 多作者（或未筛选）：仅前 LAZY_GROUPS 组渲染卡片，其余折叠按需加载（首屏提速）
        for i, (name, ws) in enumerate(raw_groups.items()):
            if i < LAZY_GROUPS:
                author_groups[name] = {
                    "works": _merge_series(ws)[:GROUP_PREVIEW],
                    "total": len(ws),
                    **_group_extras(ws),
                }
            else:
                author_groups[name] = {
                    "works": [],
                    "total": len(ws),
                    "lazy": True,
                    **_group_extras(ws),
                }

    ctx["author_groups"] = author_groups
    return templates.TemplateResponse(request, "works.html", ctx)


@router.get("/works/author/works")
def author_works_partial(
    request: Request,
    name: str = Query("", description="作者名"),
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=60),
):
    """某作者作品的 HTML 片段（作者分组懒加载用），返回 JSON。"""
    from fastapi.responses import JSONResponse

    entries = _merge_series(_safe_search(author=name))
    items = entries[offset:offset + limit]
    html = templates.TemplateResponse(request, "partials/_works_grid.html", {
        "request": request,
        "items": items,
    }).body.decode()
    return JSONResponse({
        "html": html,
        "has_more": offset + limit < len(entries),
        "total": len(entries),
    })


@router.get("/works/series")
def series_page(
    request: Request,
    name: str = Query("", description="系列名"),
    page: int = Query(1, ge=1),
):
    """系列作品页：某系列的全部作品。"""
    if not name:
        return templates.TemplateResponse(request, "series.html", {
            "request": request,
            "active_page": "works",
            "series_name": "",
            "works": [],
            "total": 0,
            "stats": get_stats(),
        })

    results = _safe_search(series=name)
    total = len(results)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    items = [_normalize_work(w) for w in results[start:start + PAGE_SIZE]]

    # 系列统计：作者 + 类型分布
    from collections import Counter
    authors: list[str] = []
    type_dist: Counter = Counter()
    for w in results:
        an = w.get("作者", "")
        if an and an not in authors:
            authors.append(an)
        ft = w.get("分类", "")
        if ft:
            type_dist[ft] += 1

    return templates.TemplateResponse(request, "series.html", {
        "request": request,
        "active_page": "works",
        "series_name": name,
        "works": items,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "authors": authors,
        "type_dist": dict(type_dist.most_common()),
        "stats": get_stats(),
    })


@router.get("/works/{work_id}")
def work_detail(request: Request, work_id: str):
    """作品详情页。"""
    from src.operations.search_op import is_adult_row

    info = get_info(work_id, "book")
    if not info:
        return templates.TemplateResponse(request, "work_detail.html", {
            "request": request,
            "active_page": "works",
            "work": None,
            "error": f"(・ω・)? 找不到这个作品呀～再检查一下 ID（{work_id}）？",
        })

    # 儿童模式：不展示成人内容
    if _kid_mode() and is_adult_row(info):
        return templates.TemplateResponse(request, "work_detail.html", {
            "request": request,
            "active_page": "works",
            "work": None,
            "error": "(・ω・)? 儿童模式下不展示该作品～",
        })

    work = _normalize_work(info)

    # 同系列相关作品（儿童模式下同样过滤成人内容）
    related = []
    if work.get("series_name"):
        for r in get_related_works(work["series_name"], exclude_id=work["id"]):
            if _kid_mode() and is_adult_row(r):
                continue
            related.append(_normalize_work(r))

    return templates.TemplateResponse(request, "work_detail.html", {
        "request": request,
        "active_page": "works",
        "work": work,
        "related": related,
        "stats": get_stats(),
    })


@router.get("/works/{work_id}/cover")
def work_cover(work_id: str):
    """作品封面图片（EPUB/PDF）。无封面或格式不支持返回 404。"""
    info = get_info(work_id, "book")
    if not info:
        return Response(status_code=404)

    file_path = info.get("文件路径", "")
    suffix = Path(file_path).suffix.lower() if file_path else ""
    if suffix not in (".epub", ".pdf"):
        return Response(status_code=404)

    cover = extract_cover(file_path)
    if not cover:
        return Response(status_code=404)

    return Response(
        content=cover,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


_APP_ALIASES = {
    "chrome": "Google Chrome",
    "book": "Books",
    "books": "Books",
    "apple books": "Books",
}


def _resolve_app(name: str) -> str:
    """常见别名 → 系统应用名（macOS open -a 用）。"""
    n = (name or "").strip()
    return _APP_ALIASES.get(n.lower(), n)


def _default_open_app(file_type: str) -> str:
    """按作品类型选择默认打开应用（可配置覆盖）。"""
    ps = (load_config().get("project_settings", {}) or {})
    if (file_type or "").strip() == "小说":
        return ps.get("open_app_book", "") or "Books"
    return ps.get("open_app_other", "") or "Chrome"


@router.post("/works/{work_id}/favorite")
def toggle_favorite(work_id: str):
    """切换作品收藏状态（本地库收藏标记）。"""
    from src.core.database import query_all_sites
    from src.core.work_manager import WorkManager

    rows = query_all_sites("SELECT favorite FROM works WHERE id = ?", (work_id,))
    if not rows:
        return JSONResponse({"success": False, "error": "(・ω・)? 作品不存在呀～"}, status_code=404)

    new_val = 0 if rows[0]["favorite"] else 1
    # update_entry_full 使用中文清单键（"收藏"），传 "是"/"否"
    WorkManager.update_entry_full(work_id, {"收藏": "是" if new_val else "否"})
    return {"success": True, "favorite": bool(new_val)}


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

    rows = _safe_search(query=q, author=author, tags=tags,
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
    import os
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


@router.put("/works/{work_id}")
async def update_work(work_id: str, request: Request):
    """编辑作品元数据：标题/作者/系列/评分/标签/简介/来源。

    注意：修改作者或系列会触发文件移动，作品 ID 可能变化（moved=true）。
    """
    from src.operations.edit_op import edit_book

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"success": False, "error": "请求格式错误"}, status_code=400)

    field_updates = {}
    for zh, key in (("标题", "title"), ("评分", "rating"),
                    ("标签", "tags"), ("简介", "description"), ("来源", "source")):
        if key in body and body[key] is not None:
            field_updates[zh] = str(body[key]).strip()
    new_author = str(body.get("author") or "").strip()
    new_series = str(body.get("series") or "").strip()

    try:
        result = edit_book(work_id, field_updates,
                           new_author=new_author, new_series=new_series)
    except Exception as exc:
        return JSONResponse({"success": False, "error": f"保存失败: {exc}"}, status_code=500)
    if result is None:
        return JSONResponse({"success": False, "error": "未找到作品"}, status_code=404)

    new_id = result.get("id", work_id)
    # update_entry_full 返回中文键 manifest（row_to_manifest）
    return {
        "success": True,
        "id": new_id,
        "title": result.get("标题", ""),
        "author": result.get("作者", ""),
        "series": result.get("系列", ""),
        "tags": result.get("标签", ""),
        "description": result.get("简介", ""),
        "source": result.get("来源", ""),
        "rating": result.get("评分", ""),
        "favorite": result.get("收藏", "否") == "是",
        "moved": new_id != work_id,
    }


@router.post("/works/{work_id}/open")
def work_open(work_id: str):
    """用指定应用打开作品文件（小说→Books，其他→Chrome，可配置）。"""
    info = get_info(work_id, "book")
    if not info:
        return JSONResponse({"success": False, "error": "(・ω・)? 作品不存在呀～"}, status_code=404)

    file_path = info.get("文件路径", "")
    if not file_path:
        return JSONResponse({"success": False, "error": "(｡•́︿•̀｡) 没有文件路径呀～"}, status_code=400)

    import os
    if not os.path.exists(file_path):
        return JSONResponse({"success": False, "error": "(｡•́︿•̀｡) 文件不存在呀～"}, status_code=404)

    app = _resolve_app(_default_open_app(info.get("分类", "")))

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", app, file_path])
        elif sys.platform == "win32":
            os.startfile(file_path)
        else:
            # Linux：优先用指定命令，找不到则 xdg-open
            import shutil
            exe = shutil.which(app)
            if exe:
                subprocess.Popen([exe, file_path])
            else:
                subprocess.Popen(["xdg-open", file_path])
        # 记录最近打开（仪表盘「最近活动」）
        from src.operations import record_open
        from src.core.site import infer_site
        record_open(work_id, info.get("标题", ""), infer_site(info.get("来源", "") or ""))
        return {"success": True}
    except Exception as e:
        return JSONResponse({"success": False, "error": f"(｡•́︿•̀｡) 打开失败呀～ {e}"}, status_code=500)
