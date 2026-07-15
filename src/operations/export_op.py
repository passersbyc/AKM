"""export 操作 - 作品导出入口。"""
from pathlib import Path

from src.core.work_manager import WorkManager
from src.core.author_manager import list_all
from src.export import export_works
from src.export.models import ExportRequest


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
