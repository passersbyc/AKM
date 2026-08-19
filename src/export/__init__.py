import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from .models import ExportRequest, ExportPlan, ExportResult
from .collector import collect_rows
from .merger import merge_series_group, merge_by_completeness, merge_epubs, merge_pdfs, MergeMeta
from .formatter import format_as_folder, format_as_zip
from src.core.converter import convert_to_epub
from src.core.logging import logger


def export_works(rows: list[dict], request: ExportRequest) -> ExportResult:
    if request.mode == "all":
        return export_all_works(rows, request)

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

        if request.mode in ("id", "mylikeauthor") and len(request.author_ids) > 1:
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
                                                       plan.is_tag_mode, author_name)
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
            try:
                shutil.rmtree(temp_dir)
            except BaseException:
                # 临时目录清理失败（如运行环境文件保护拦截）时静默忽略，残留无碍
                pass


def _copy_standalone(standalone: list[dict], content_dir: Path,
                     progress: object | None = None) -> int:
    count = 0
    for row in standalone:
        src = Path(row.get("文件路径", ""))
        if not src.exists():
            if progress:
                progress.advance(progress.task_ids[0])
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
        if progress:
            progress.advance(progress.task_ids[0])
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

        if request.mode in ("id", "mylikeauthor") and len(request.author_ids) > 1:
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
                    plan.is_tag_mode, request.query, progress
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
                       content_dir: Path, is_tag_mode: bool, query: str,
                       progress: object | None = None) -> int:
    epub_suffixes = {'.txt', '.doc', '.docx'}
    work = content_dir / "_epub_work"
    work.mkdir(exist_ok=True)
    count = 0

    try:
        # 1. Standalone: convert to epub with clean name, copy unsupported as-is
        for row in standalone:
            src = Path(row.get("文件路径", ""))
            if not src.exists():
                if progress:
                    progress.advance(progress.task_ids[0])
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
            if progress:
                progress.advance(progress.task_ids[0])

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

            if progress:
                progress.advance(progress.task_ids[0])

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


def export_all_works(rows: list[dict], request: ExportRequest) -> ExportResult:
    """全库导出：按 {author}/{type} 结构组织——作者是文件夹，类型是压缩包（或目录）。

    覆盖式同步：同名 zip/目录先清理再生成，始终为最新快照；清理失败时追加时间戳兜底。
    """
    plan = collect_rows(rows, request)
    if not plan.standalone and not plan.series_groups:
        return ExportResult(False, 0, error="没有可导出的作品")

    author_groups = _split_plan_by_author(plan)
    if not author_groups:
        return ExportResult(False, 0, error="没有可导出的作者")

    library_root = request.dest_dir
    try:
        _validate_export_dest(library_root)
    except ValueError as e:
        return ExportResult(False, 0, error=str(e))
    library_root.mkdir(parents=True, exist_ok=True)
    temp_root = request.dest_dir / "_library_all_tmp"
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)

    total = len(author_groups)
    progress = _show_progress(total)
    count = 0
    succeeded = 0
    errors: list[str] = []
    try:
        sorted_authors = sorted(author_groups.items())

        def _process_author(author_name: str, standalone: list[dict],
                            series_groups: dict[str, list[dict]]) -> tuple[str, int, Path]:
            author_safe = _safe_name(author_name) or "unknown"
            rows_all = list(standalone)
            for srows in series_groups.values():
                rows_all.extend(srows)

            # 按类型分组
            type_groups: dict[str, list[dict]] = {}
            for row in rows_all:
                ft = row.get("分类", "") or "未知"
                type_groups.setdefault(ft, []).append(row)

            author_tmp = temp_root / author_safe
            author_tmp.mkdir(parents=True)
            n = 0
            try:
                for ft, ft_rows in sorted(type_groups.items()):
                    ft_safe = _safe_name(ft) or "未知"
                    type_dir = author_tmp / ft_safe
                    type_dir.mkdir(exist_ok=True)
                    # 类型内拆分：standalone 平铺复制，系列作品合并为合订本
                    ft_standalone, ft_series = _classify_by_series(ft_rows)
                    n += _copy_standalone(ft_standalone, type_dir)
                    n += merge_series_group(ft_series, type_dir,
                                            plan.is_tag_mode, author_name)

                # 作者 = 文件夹；类型 = 压缩包（zip 模式）或类型子目录（folder 模式）
                author_final = library_root / author_safe
                author_final = _replace_dest(author_final, is_dir=True)

                if request.output_format == "folder":
                    shutil.move(str(author_tmp), str(author_final))
                else:
                    author_final.mkdir(parents=True)
                    for ft in sorted(type_groups):
                        ft_safe = _safe_name(ft) or "未知"
                        zip_final = _replace_dest(author_final / f"{ft_safe}.zip", is_dir=False)
                        shutil.make_archive(
                            base_name=str(zip_final.with_suffix("")),
                            format="zip",
                            root_dir=str(author_tmp / ft_safe),
                            base_dir=".",
                        )
            finally:
                shutil.rmtree(author_tmp, ignore_errors=True)
            return author_name, n, author_final

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(_process_author, name, st, sg): name
                for name, (st, sg) in sorted_authors
            }
            for future in as_completed(futures):
                try:
                    author_name, n, final = future.result()
                    count += n
                    succeeded += 1
                    if progress:
                        _update_progress_desc(progress, author_name, succeeded, total)
                        progress.advance(progress.task_ids[0])
                except Exception as e:
                    name = futures[future]
                    errors.append(f"{name}: {e}")
                    logger.error(f"导出作者 {name} 失败: {e}")
    finally:
        if progress:
            progress.stop()
        shutil.rmtree(temp_root, ignore_errors=True)

    if succeeded == 0:
        return ExportResult(False, 0, error="全部作者导出失败: " + "; ".join(errors))

    if errors:
        logger.warning(f"部分作者导出失败: {errors}")
    return ExportResult(True, count, library_root, results={
        "succeeded": succeeded, "total": total, "errors": errors,
    })


def _classify_by_series(rows: list[dict]) -> tuple[list[dict], dict[str, list[dict]]]:
    """按系列字段把行拆分为 standalone 与系列分组（系列内按 ID 排序）。"""
    standalone = []
    series_groups: dict[str, list[dict]] = {}
    for row in rows:
        series = (row.get("系列", "") or "").strip()
        if series:
            series_groups.setdefault(series, []).append(row)
        else:
            standalone.append(row)
    for sg in series_groups.values():
        sg.sort(key=lambda x: x.get("ID", ""))
    return standalone, series_groups


def _validate_export_dest(dest_dir: Path) -> None:
    """禁止导出目标落在源库/项目根内，防止覆盖式删除误删源数据。

    all 模式会按作者覆盖式重建目录/zip，若 dest 误配成源库或项目根，
    会把原作品/代码一并删掉。此处拦一道。
    """
    from src.core.config import get_library_path, get_project_root
    dest = dest_dir.resolve()
    for forbidden in (get_library_path().resolve(), get_project_root().resolve()):
        if dest == forbidden or forbidden in dest.parents:
            raise ValueError(
                f"导出目标 {dest} 落在受保护目录 {forbidden} 内或就是该目录，"
                f"覆盖式导出会删除源数据，已拒绝执行"
            )


def _replace_dest(final: Path, is_dir: bool) -> Path:
    """覆盖式替换目标；失败（文件保护等）时追加时间戳兜底。"""
    try:
        if final.exists():
            if is_dir:
                shutil.rmtree(final)
            else:
                final.unlink()
        return final
    except BaseException:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return final.with_name(f"{final.stem}-{stamp}{final.suffix}")
