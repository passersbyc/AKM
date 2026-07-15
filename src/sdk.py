"""精简 SDK — 仅保留 cdbook 批量导入和独立辅助函数。"""
from pathlib import Path

from src.core.registry import _flush_id_registry
from src.core.reindex import reindex_for_source
from src.core.filetype import determine_file_type
from src.core.logging import logger
from src.domain.cdbook import parse_cdbook_filename, detect_cdbook_series
from src.core.importer import import_one
from src.core.config import get_convert_setting


def batch_import_cdbook(directory: str, dry_run: bool = False,
                        limit: int = 0, target_format: str = "epub") -> dict:
    root = Path(directory)
    if not root.is_dir():
        return {"success": False, "error": f"目录不存在: {directory}"}

    all_files = []
    supported_suffixes = ('.doc', '.docx', '.txt', '.epub', '.pdf', '.mobi', '.azw3', '.fb2', '.cbz', '.cbr')
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in supported_suffixes:
            if path.name.startswith('.') or path.name == '提取文件名.bat':
                continue
            all_files.append(path)

    if limit > 0:
        all_files = all_files[:limit]

    file_metas = []
    by_folder = {}
    for fp in all_files:
        folder_tag = fp.parent.name if fp.parent != root else ""
        meta = parse_cdbook_filename(fp.name, fallback_tag=folder_tag)
        meta["path"] = str(fp)
        meta["folder"] = str(fp.parent.relative_to(root)) if fp.parent != root else ""
        file_metas.append(meta)
        by_folder.setdefault(meta["folder"], []).append(meta)

    for folder, metas in by_folder.items():
        detect_cdbook_series(metas)

    def _cdbook_sort_key(m):
        series = m.get("series", "")
        order = m.get("order", "")
        title = m.get("title", "")
        if series and order:
            try:
                return (0, series, int(order), title)
            except ValueError:
                return (0, series, 0, title)
        elif series:
            return (1, series, 0, title)
        else:
            return (2, "", 0, title)
    file_metas.sort(key=_cdbook_sort_key)

    doc_count = sum(1 for m in file_metas if Path(m["path"]).suffix.lower() in ('.doc', '.docx'))
    if doc_count > 0:
        logger.info(f"检测到 {doc_count} 个 Word 文档，将自动转换为 epub 格式")

    series_set = set()
    for m in file_metas:
        if m["series"]:
            series_set.add(m["series"])

    if dry_run:
        lines = []
        for m in file_metas[:50]:
            s = f"[{m['tag']}]"
            if m['extra_tags']:
                s += f" [{m['extra_tags']}]"
            s += f" {m['title']}"
            if m['chapter']:
                s += f" ({m['chapter']})"
            if m['series']:
                s += f" → 系列:{m['series']}  #{m.get('order','-')}"
            if m['author']:
                s += f" 作者:{m['author']}"
            lines.append(s)
        return {
            "success": True, "dry_run": True,
            "total_files": len(all_files),
            "series_count": len(series_set),
            "preview": lines,
        }

    success = 0
    skipped = 0
    errors = 0
    error_details = []
    imported_ids = []

    for i, meta in enumerate(file_metas):
        fp = Path(meta["path"])
        convert = fp.suffix.lower() in ('.doc', '.docx')
        try:
            tag_list = [meta["tag"]] if meta["tag"] else []
            if meta["extra_tags"]:
                tag_list.extend(meta["extra_tags"].split(","))
            tags_str = ",".join(tag_list)
            result = import_one(
                file_path=str(fp),
                author=meta["author"] or "cdbook",
                series=meta.get("series", ""),
                tags=tags_str,
                source="cdbook",
                convert_doc=convert,
                convert_traditional=True,
                title=meta["title"],
                target_format=target_format,
            )
            if result.success:
                success += 1
                imported_ids.append(result.book_id)
            elif result.duplicate_of:
                skipped += 1
            else:
                errors += 1
                error_details.append({"file": str(fp), "error": result.error})
        except Exception as e:
            errors += 1
            error_details.append({"file": str(fp), "error": str(e)})
        if (i + 1) % 100 == 0:
            logger.info(f"进度: {i+1}/{len(file_metas)} 成功:{success} 跳过:{skipped} 失败:{errors}")

    reindex_for_source("cdbook")
    _flush_id_registry()

    return {
        "success": True, "total": len(file_metas),
        "imported": success, "skipped": skipped, "errors": errors,
        "error_details": error_details[:20], "series_count": len(series_set),
        "imported_ids": imported_ids[:5],
    }


def import_files_batch(files: list[str], author: str = "", series: str = "",
                       tags: str = "", source: str = "", favorited: bool = False,
                       rating: float = 0.0, description: str = "",
                       target_format: str = "epub") -> list:
    from src.core.importer import import_batch as _import_batch
    from src.core.registry import _flush_id_registry as _flush
    convert_traditional = get_convert_setting()
    results = _import_batch(files, author, series, tags, source, favorited,
                             rating, description, title="",
                             convert_traditional=convert_traditional,
                             target_format=target_format)
    if source in ("cdbook", "local"):
        reindex_for_source(source)
    _flush()
    return results


def batch_import_folder(directory: str, dry_run: bool = False,
                        limit: int = 0, target_format: str = "epub",
                        tags: str = "", source: str = "") -> dict:
    """按 {author}/{series}/{work} 结构批量导入文件夹。"""
    root = Path(directory)
    if not root.is_dir():
        return {"success": False, "error": f"目录不存在: {directory}"}

    supported_suffixes = ('.doc', '.docx', '.txt', '.epub', '.pdf', '.mobi', '.azw3', '.fb2', '.cbz', '.cbr')
    author_name = root.name

    file_metas = []
    series_set = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in supported_suffixes:
            continue
        if path.name.startswith('.') or path.name == '提取文件名.bat':
            continue
        if limit > 0 and len(file_metas) >= limit:
            break

        rel = path.parent.relative_to(root)
        series_name = str(rel) if str(rel) != "." else ""
        title = path.stem

        meta = {
            "path": str(path),
            "author": author_name,
            "title": title,
            "series": series_name,
        }
        if series_name:
            series_set.add(series_name)
        file_metas.append(meta)

    if dry_run:
        lines = []
        for m in file_metas[:50]:
            s = f"{m['title']}"
            if m['series']:
                s += f" → 系列:{m['series']}"
            s += f"  作者:{m['author']}"
            lines.append(s)
        return {
            "success": True, "dry_run": True,
            "total_files": len(file_metas),
            "series_count": len(series_set),
            "preview": lines,
        }

    success = 0
    skipped = 0
    errors = 0
    error_details = []
    imported_ids = []

    convert_traditional = get_convert_setting()
    if convert_traditional:
        logger.info("繁体转简体: 已启用")

    for i, meta in enumerate(file_metas):
        fp = Path(meta["path"])
        convert = fp.suffix.lower() in ('.doc', '.docx')
        try:
            result = import_one(
                file_path=str(fp),
                author=meta["author"],
                series=meta.get("series", ""),
                tags=tags,
                source=source or "local",
                convert_doc=convert,
                convert_traditional=convert_traditional,
                title=meta["title"],
                target_format=target_format,
            )
            if result.success:
                success += 1
                imported_ids.append(result.book_id)
            elif result.duplicate_of:
                skipped += 1
            else:
                errors += 1
                error_details.append({"file": str(fp), "error": result.error})
        except Exception as e:
            errors += 1
            error_details.append({"file": str(fp), "error": str(e)})
        if (i + 1) % 100 == 0:
            logger.info(f"进度: {i+1}/{len(file_metas)} 成功:{success} 跳过:{skipped} 失败:{errors}")

    _flush_id_registry()

    return {
        "success": True, "total": len(file_metas),
        "imported": success, "skipped": skipped, "errors": errors,
        "error_details": error_details[:20], "series_count": len(series_set),
        "imported_ids": imported_ids[:5],
    }
