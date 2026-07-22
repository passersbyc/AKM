"""作品路由 — /works 列表+搜索, /works/{work_id} 详情, /works/{work_id}/cover 封面。"""
from __future__ import annotations

from fastapi import APIRouter, Request, Query
from fastapi.responses import Response
from src.core.database import short_id

from src.operations import search_works, get_info, get_related_works
from src.web.app import templates
from src.web.cover import extract_epub_cover

router = APIRouter()

PAGE_SIZE = 24

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
    return w


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
    items = [_normalize_work(w) for w in results[start:start + PAGE_SIZE]]

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

    work = _normalize_work(info)

    # 同系列相关作品
    related = []
    if work.get("series_name"):
        for r in get_related_works(work["series_name"], exclude_id=work["id"]):
            related.append(_normalize_work(r))

    return templates.TemplateResponse(request, "work_detail.html", {
        "request": request,
        "active_page": "works",
        "work": work,
        "related": related,
    })


@router.get("/works/{work_id}/cover")
async def work_cover(work_id: str):
    """EPUB 封面图片。无封面或非 EPUB 返回 404。"""
    info = get_info(work_id, "book")
    if not info:
        return Response(status_code=404)

    file_path = info.get("文件路径", "")
    if not file_path or not file_path.lower().endswith(".epub"):
        return Response(status_code=404)

    cover = extract_epub_cover(file_path)
    if not cover:
        return Response(status_code=404)

    return Response(
        content=cover,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
