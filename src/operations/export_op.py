"""export 操作 - 作品导出入口。"""
from pathlib import Path

from src.core.work_manager import WorkManager
from src.core.author_manager import list_all
from src.export import export_works
from src.export.models import ExportRequest
from src.core.logging import logger


def export_by_query(
    query: str,
    dest_dir: Path,
    export_name: str = "",
    mode: str = "author",
    filter_type: str | None = None,
    limit: int = 0,
    output_format: str = "folder",
    author_ids: list[str] | None = None,
    favorited_only: bool = False,
) -> dict:
    final_author_ids = list(author_ids or [])
    if favorited_only:
        fav_ids = [r.get("id", "") for r in list_all() if r.get("favorite")]
        if final_author_ids:
            final_author_ids = [aid for aid in final_author_ids if aid in fav_ids]
        else:
            final_author_ids = fav_ids

    rows = WorkManager.read()
    request = ExportRequest(
        query=query,
        dest_dir=dest_dir,
        export_name=export_name or query,
        mode=mode,
        filter_type=filter_type,
        limit=limit,
        output_format=output_format,
        author_ids=final_author_ids,
        favorited_only=favorited_only,
    )
    result = export_works(rows, request)
    return {
        "success": result.success,
        "exported": result.exported_count,
        "destination": str(result.destination),
        "results": result.results,
        "error": result.error,
    }


def export_work(target: str, dest_dir: Path,
                output_format: str = "folder") -> dict:
    from src.cli.matcher import resolve_work
    from src.core.work_repository import get_by_id

    work = resolve_work(target)
    if not work:
        return {"success": False, "exported": 0, "error": f"未找到作品: {target}"}

    work_id = work.get("id", "")
    row = get_by_id(work_id)
    if not row:
        return {"success": False, "exported": 0, "error": f"未找到作品: {target}"}

    title = row.get("标题", "") or "untitled"
    request = ExportRequest(
        query=target, dest_dir=dest_dir, export_name=title,
        mode="work", output_format=output_format,
    )
    result = export_works([row], request)
    return {
        "success": result.success,
        "exported": result.exported_count,
        "destination": str(result.destination),
        "error": result.error,
    }


def export_author(target: str, dest_dir: Path,
                  filter_type: str | None = None, limit: int = 0,
                  output_format: str = "folder") -> dict:
    from src.cli.matcher import resolve_author

    author = resolve_author(target)
    if not author:
        return {"success": False, "exported": 0, "error": f"未找到作者: {target}"}

    author_id = author.get("id", "")
    author_name = author.get("name", target)
    rows = WorkManager.get_by_author_local_id(author_id)
    if not rows:
        return {"success": False, "exported": 0, "error": f"作者 {author_name} 没有作品"}

    request = ExportRequest(
        query=author_name, dest_dir=dest_dir, export_name=author_name,
        mode="author", filter_type=filter_type, limit=limit,
        output_format=output_format,
    )
    result = export_works(rows, request)
    return {
        "success": result.success,
        "exported": result.exported_count,
        "destination": str(result.destination),
        "error": result.error,
    }


def export_mylikeauthor(dest_dir: Path,
                         filter_type: str | None = None, limit: int = 0,
                         output_format: str = "folder") -> dict:
    from src.operations import list_items

    authors = list_items("author")["items"]
    fav_authors = [a for a in authors if a.get("favorite", False)]
    if not fav_authors:
        return {"success": False, "exported": 0, "error": "没有收藏的作者"}

    all_rows = []
    fav_ids = []
    for a in fav_authors:
        aid = a.get("id", "")
        fav_ids.append(aid)
        rows = WorkManager.get_by_author_local_id(aid)
        all_rows.extend(rows)

    if not all_rows:
        return {"success": False, "exported": 0, "error": "收藏作者没有作品"}

    export_name = "收藏作者作品"
    request = ExportRequest(
        query="", dest_dir=dest_dir, export_name=export_name,
        mode="mylikeauthor", filter_type=filter_type, limit=limit,
        output_format=output_format, author_ids=fav_ids,
    )
    result = export_works(all_rows, request)
    return {
        "success": result.success,
        "exported": result.exported_count,
        "destination": str(result.destination),
        "error": result.error,
    }


def export_mylikeworks(dest_dir: Path,
                       output_format: str = "folder") -> dict:
    rows = WorkManager.read()
    fav_rows = [r for r in rows if r.get("收藏", "") == "是"]
    if not fav_rows:
        return {"success": False, "exported": 0, "error": "没有收藏的作品"}

    export_name = "收藏作品"
    request = ExportRequest(
        query="", dest_dir=dest_dir, export_name=export_name,
        mode="mylikeworks", output_format=output_format,
    )
    result = export_works(fav_rows, request)
    return {
        "success": result.success,
        "exported": result.exported_count,
        "destination": str(result.destination),
        "error": result.error,
    }
