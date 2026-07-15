"""import 操作 - 文件导入入口。"""
from pathlib import Path

from src.core.work_manager import WorkManager
from src.core.importer import import_one as _import_one, ImportResult
from src.core.registry import _flush_id_registry

def register_entry(entry: dict) -> None:
    WorkManager.append(entry)


def import_file(
    file_path: str,
    author: str = "",
    series: str = "",
    tags: str = "",
    source: str = "",
    favorited: bool = False,
    rating: float = 0.0,
    description: str = "",
    convert_doc: bool = True,
    convert_traditional: bool = False,
    title: str = "",
    user_id: str = "",
    source_status: str = "ok",
    target_format: str = "epub",
) -> ImportResult:
    return _import_one(
        file_path=file_path,
        author=author,
        series=series,
        tags=tags,
        source=source,
        favorited=favorited,
        rating=rating,
        description=description,
        convert_doc=convert_doc,
        convert_traditional=convert_traditional,
        title=title,
        user_id=user_id,
        source_status=source_status,
        target_format=target_format,
    )


def import_files(
    files: list[str],
    author: str = "",
    series: str = "",
    tags: str = "",
    source: str = "",
    favorited: bool = False,
    rating: float = 0.0,
    description: str = "",
    convert_doc: bool = True,
    convert_traditional: bool = False,
    title: str = "",
    user_id: str = "",
    source_status: str = "ok",
    target_format: str = "epub",
) -> list[ImportResult]:
    return _import_batch(
        files=files,
        author=author,
        series=series,
        tags=tags,
        source=source,
        favorited=favorited,
        rating=rating,
        description=description,
        convert_doc=convert_doc,
        convert_traditional=convert_traditional,
        title=title,
        user_id=user_id,
        source_status=source_status,
        target_format=target_format,
    )


def _import_batch(
    files: list[str],
    author: str = "",
    series: str = "",
    tags: str = "",
    source: str = "",
    favorited: bool = False,
    rating: float = 0.0,
    description: str = "",
    convert_doc: bool = True,
    convert_traditional: bool = False,
    title: str = "",
    user_id: str = "",
    source_status: str = "ok",
    target_format: str = "epub",
) -> list[ImportResult]:
    from src.core.importer import import_batch
    results = import_batch(
        files=files,
        author=author,
        series=series,
        tags=tags,
        source=source,
        favorited=favorited,
        rating=rating,
        description=description,
        source_status=source_status,
        convert_doc=convert_doc,
        convert_traditional=convert_traditional,
        title=title,
        user_id=user_id,
        target_format=target_format,
    )
    _flush_id_registry()
    return results
