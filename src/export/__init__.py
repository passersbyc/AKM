import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .models import ExportRequest, ExportPlan, ExportResult
from .collector import collect_rows
from .merger import merge_series_group, merge_by_completeness, merge_epubs, merge_pdfs, MergeMeta
from .formatter import format_as_folder, format_as_zip
from src.core.converter import convert_to_epub
from src.core.logging import logger


def export_works(rows: list[dict], request: ExportRequest) -> ExportResult:
    plan = collect_rows(rows, request)

    if not plan.standalone and not plan.series_groups:
        return ExportResult(False, 0, error="未找到要导出的任何作品")

    if request.output_format == "completeness":
        return _do_completeness(plan, request)

    if request.output_format == "epub":
        return _do_epub_export(plan, request)

    return _do_standard(plan, request)


from src.domain.cdbook import normalize_series_name as _safe_name


def _count_total(plan: ExportPlan, author_groups: dict | None = None) -> int:
    if author_groups:
        return len(author_groups)
    return max(len(plan.standalone) + len(plan.series_groups), 1)


def _show_progress(total: int) -> object | None:
    try:
        from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn
        progress = Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeRemainingColumn(),
        )
        progress.add_task("[cyan]导出中...", total=total)
        progress.start()
        return progress
    except ImportError:
        return None


def _update_progress_desc(progress: object | None, author_name: str, index: int, total: int) -> None:
    if progress:
        progress.update(progress.task_ids[0],
                       description=f"[cyan]{index}/{total} {author_name}")


def _do_completeness(plan: ExportPlan, request: ExportRequest) -> ExportResult:
    all_type_rows = 0
    for ft, tg in plan.type_groups.items():
        tg_rows = list(tg.standalone)
        for srows in tg.series_groups.values():
            tg_rows.extend(srows)
        all_type_rows += len(tg_rows)

        suffixes = set((r.get("后缀", "") or "").lower() for r in tg_rows)
        if len(suffixes) > 1:
            return ExportResult(False, 0, error=f"分类 '{ft}' 下存在混合格式 {suffixes}，无法以 completeness 模式导出")
        if not suffixes or not list(suffixes)[0]:
            return ExportResult(False, 0, error=f"分类 '{ft}' 下存在未知格式，无法导出")

    if all_type_rows == 0:
        return ExportResult(False, 0, error="没有可合并的作品")

    safe_name = _safe_name(request.export_name)
    progress = _show_progress(len(plan.type_groups))
    try:
        results = {}
        for i, (ft, tg) in enumerate(plan.type_groups.items()):
            _update_progress_desc(progress, ft, i + 1, len(plan.type_groups))
            type_results = merge_by_completeness(
                {ft: tg}, request.dest_dir, safe_name,
                plan.is_tag_mode, request.query
            )
            results.update(type_results)
            if progress:
                progress.advance(progress.task_ids[0])
    finally:
        if progress:
            progress.stop()

    count = sum(1 for r in results.values() if r.get("status") == "merged")
    if count == 0:
        return ExportResult(False, 0, error="所有分类合并均失败")

    return ExportResult(True, count, request.dest_dir, results=results)


def _do_standard(plan: ExportPlan, request: ExportRequest) -> ExportResult:
    safe_name = _safe_name(request.export_name)
    temp_dir = request.dest_dir / f"_{safe_name}_temp"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)

    try:
        content_dir = temp_dir / safe_name
        content_dir.mkdir()

        if request.mode == "id" and len(request.author_ids) > 1:
            author_groups = _split_plan_by_author(plan)
            total = _count_total(plan, author_groups)
            progress = _show_progress(total)
            try:
                sorted_authors = sorted(author_groups.items())
                count = 0

                def _process_author(idx: int, author_name: str, standalone, series_groups):
                    author_safe = _safe_name(author_name)
                    author_dir = content_dir / author_safe
                    author_dir.mkdir(exist_ok=True)
                    result_count = _copy_standalone(standalone, author_dir)
                    result_count += merge_series_group(series_groups, author_dir,
                                                       plan.is_tag_mode, request.query)
                    if progress:
                        _update_progress_desc(progress, author_name, idx + 1, total)
                        progress.advance(progress.task_ids[0])
                    return result_count

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {
                        executor.submit(_process_author, idx, author_name, standalone, series_groups): author_name
                        for idx, (author_name, (standalone, series_groups)) in enumerate(sorted_authors)
                    }
                    for future in as_completed(futures):
                        try:
                            count += future.result()
                        except Exception as e:
                            logger.error(f"导出作者 {futures[future]} 失败: {e}")
            finally:
                if progress:
                    progress.stop()
        else:
            total = _count_total(plan)
            progress = _show_progress(total)
            try:
                count = _copy_standalone(plan.standalone, content_dir, progress)
                count += merge_series_group(
                    plan.series_groups, content_dir,
                    plan.is_tag_mode, request.query, progress
                )
            finally:
                if progress:
                    progress.stop()

        if request.output_format == "folder":
            dest = format_as_folder(content_dir, request.dest_dir, safe_name)
        else:
            dest = format_as_zip(temp_dir, request.dest_dir, safe_name)

        return ExportResult(True, count, dest)
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)


def _copy_standalone(standalone: list[dict], content_dir: Path,
                     progress: object | None = None) -> int:
    count = 0
    for row in standalone:
        src = Path(row.get("文件路径", ""))
        if not src.exists():
            continue
        filename = row.get("标题", "") or src.stem
        if not filename.lower().endswith(src.suffix.lower()):
            filename += src.suffix
        filename = _safe_name(filename)
        try:
            shutil.copy2(src, content_dir / filename)
            count += 1
        except Exception as e:
            logger.error(f"复制文件失败 {filename}: {e}")
    return count


def _do_epub_export(plan: ExportPlan, request: ExportRequest) -> ExportResult:
    safe_name = _safe_name(request.export_name)
    work_dir = request.dest_dir / f"_{safe_name}_epub_work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    try:
        content_dir = work_dir / safe_name
        content_dir.mkdir()

        if request.mode == "id" and len(request.author_ids) > 1:
            author_groups = _split_plan_by_author(plan)
            total = _count_total(plan, author_groups)
            progress = _show_progress(total)
            try:
                sorted_authors = sorted(author_groups.items())
                count = 0
                for idx, (author_name, (standalone, series_groups)) in enumerate(sorted_authors):
                    _update_progress_desc(progress, author_name, idx + 1, total)
                    author_safe = _safe_name(author_name)
                    author_dir = content_dir / author_safe
                    author_dir.mkdir(exist_ok=True)
                    count += _epub_export_group(
                        standalone, series_groups, author_dir,
                        plan.is_tag_mode, author_name
                    )
                    if progress:
                        progress.advance(progress.task_ids[0])
            finally:
                if progress:
                    progress.stop()
        else:
            total = _count_total(plan)
            progress = _show_progress(total)
            try:
                count = _epub_export_group(
                    plan.standalone, plan.series_groups, content_dir,
                    plan.is_tag_mode, request.query
                )
            finally:
                if progress:
                    progress.stop()

        dest = format_as_folder(content_dir, request.dest_dir, safe_name)
        return ExportResult(True, count, dest)
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir)


def _epub_export_group(standalone: list[dict], series_groups: dict[str, list[dict]],
                       content_dir: Path, is_tag_mode: bool, query: str) -> int:
    epub_suffixes = {'.txt', '.doc', '.docx'}
    work = content_dir / "_epub_work"
    work.mkdir(exist_ok=True)
    count = 0

    try:
        # 1. Standalone: convert to epub with clean name, copy unsupported as-is
        for row in standalone:
            src = Path(row.get("文件路径", ""))
            if not src.exists():
                continue
            title = row.get("标题", "") or src.stem
            suffix = src.suffix.lower()
            if suffix in epub_suffixes:
                dest = content_dir / _safe_name(f"{title}.epub")
                try:
                    convert_to_epub(src, output_path=dest, title=title, author=row.get("作者", ""))
                    count += 1
                except Exception as e:
                    logger.error(f"EPUB 转换失败 {title}: {e}")
            else:
                shutil.copy2(src, content_dir / _safe_name(f"{title}{suffix}"))
                count += 1

        # 2. Series: convert each to epub, then merge (PDF series merged separately)
        for series_name, srows in series_groups.items():
            srows_sorted = sorted(srows, key=lambda x: x.get("ID", ""))
            series_epubs = []
            series_pdfs = []
            book_metas = []
            for row in srows_sorted:
                src = Path(row.get("文件路径", ""))
                if not src.exists():
                    continue
                title = row.get("标题", "") or src.stem
                suffix = src.suffix.lower()
                if suffix in epub_suffixes:
                    tmp_epub = work / _safe_name(f"{title}.epub")
                    try:
                        convert_to_epub(src, output_path=tmp_epub, title=title, author=row.get("作者", ""))
                        series_epubs.append(tmp_epub)
                        book_metas.append(MergeMeta(book_title=title, book_author=row.get("作者", "")))
                    except Exception as e:
                        logger.error(f"EPUB 转换失败 {title}: {e}")
                elif suffix == ".pdf":
                    series_pdfs.append(src)
                else:
                    dest = content_dir / _safe_name(f"{title}{suffix}")
                    shutil.copy2(src, dest)
                    count += 1

            if series_epubs:
                author_name = "Tag_Export" if is_tag_mode else query
                merged_output = content_dir / _safe_name(f"{series_name}.epub")
                if merge_epubs(series_epubs, merged_output, series_name, author_name, book_metas=book_metas):
                    count += 1
                else:
                    shutil.copy2(series_epubs[0], merged_output)
                    count += 1
            elif series_pdfs:
                merged_output = content_dir / _safe_name(f"{series_name}.pdf")
                if merge_pdfs(series_pdfs, merged_output):
                    count += 1
                else:
                    for pdf in series_pdfs:
                        dest = content_dir / _safe_name(f"{pdf.stem}.pdf")
                        shutil.copy2(pdf, dest)
                        count += 1

    finally:
        shutil.rmtree(work, ignore_errors=True)

    return count


def _split_plan_by_author(plan: ExportPlan) -> dict[str, tuple[list[dict], dict[str, list[dict]]]]:
    all_rows = list(plan.standalone)
    for srows in plan.series_groups.values():
        all_rows.extend(srows)

    result: dict[str, tuple[list[dict], dict[str, list[dict]]]] = {}
    for row in all_rows:
        author = row.get("作者", "").strip() or "unknown"
        series = row.get("系列", "").strip()
        if author not in result:
            result[author] = ([], {})
        s_list, sg_dict = result[author]
        if series:
            sg_dict.setdefault(series, []).append(row)
        else:
            s_list.append(row)

    return result
