"""导入路由 — /import 网页导入作品文件。"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse

from src.sdk import import_files_batch
from src.operations import get_stats
from src.operations.stats_op import invalidate_stats
from src.web.app import templates

router = APIRouter()


def _render(request: Request, *, results=None, error="", submitted=None):
    from src.core.database import short_id, query_all_sites
    recent = sorted(
        query_all_sites(
            "SELECT id, title, file_type, imported_at FROM works "
            "WHERE imported_at != ''"),
        key=lambda r: r["imported_at"], reverse=True)[:5]
    for row in recent:
        row["short_id"] = short_id(row["id"])
    return templates.TemplateResponse(request, "import.html", {
        "request": request,
        "active_page": "import",
        "results": results or [],
        "error": error,
        "submitted": submitted or {},
        "recent": recent,
        "stats": get_stats(),
    })


@router.get("/import")
def import_page(request: Request):
    """导入页。"""
    return _render(request)


@router.post("/import")
async def import_submit(
    request: Request,
    files: list[UploadFile] = File(...),
    author: str = Form(""),
    series: str = Form(""),
    tags: str = Form(""),
    source: str = Form(""),
    rating: float = Form(0.0),
    description: str = Form(""),
    favorite: str = Form(""),
    target_format: str = Form("epub"),
):
    """上传并导入作品文件。"""
    if not (0.0 <= rating <= 10.0):
        return _render(request, error="(｡•́︿•̀｡) 评分必须在 0-10 之间哦！")
    if not files:
        return _render(request, error="(・ω・)? 还没有选择任何文件呢～")

    submitted = {
        "author": author, "series": series, "tags": tags, "source": source,
        "rating": rating, "description": description,
        "favorite": favorite, "target_format": target_format,
    }

    tmp = Path(tempfile.mkdtemp(prefix="akm_import_"))
    saved: list[str] = []
    try:
        for f in files:
            if not f.filename:
                continue
            dest = tmp / Path(f.filename).name
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            saved.append(str(dest))
    finally:
        pass

    if not saved:
        shutil.rmtree(tmp, ignore_errors=True)
        return _render(request, error="(・ω・)? 没有有效的文件呢～", submitted=submitted)

    results = import_files_batch(
        files=saved,
        author=author.strip() or "佚名",
        series=series.strip(),
        tags=tags.strip(),
        source=source.strip(),
        favorited=favorite == "on",
        rating=rating,
        description=description.strip(),
        target_format=target_format,
    )
    invalidate_stats()
    shutil.rmtree(tmp, ignore_errors=True)

    return _render(request, results=results, submitted=submitted)


@router.get("/import/supported")
def import_supported(request: Request):
    """支持的导入格式说明（JSON，供前端提示）。"""
    return JSONResponse({
        "formats": ["epub", "pdf", "mobi", "azw3", "fb2", "txt", "doc", "docx", "cbz", "cbr"],
    })
