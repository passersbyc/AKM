import argparse
import json
import re
from pathlib import Path
from src.cli.core import BaseCommand
from src.core.work_manager import WorkManager
from src.core.logging import logger
from src.core.config import get_project_root
from src.domain.cdbook import normalize_series_name

SOURCE_CSV = "/Users/passersbyc/代码/本地化书籍管理系统/library_manifest.csv"
LIKES_JSON = "/Users/passersbyc/代码/本地化书籍管理系统/pixiv_likes_data.json"
SERIES_ORDER_JSON = "/Users/passersbyc/代码/本地化书籍管理系统/series_order_cache.json"


class MigrateCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "migrate"

    @property
    def description(self) -> str:
        return "从旧系统迁移数据到当前系统"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际迁移")
        parser.add_argument("--limit", type=int, default=0, help="限制迁移数量（测试用）")
        parser.add_argument("-a", "--author", type=str, help="只迁移指定作者的书籍")
        parser.add_argument("-s", "--series", type=str, help="只迁移指定系列的书籍（基于series_order_cache匹配）")
        parser.add_argument("--no-likes", action="store_true", help="不导入点赞数据")
        parser.add_argument("--no-series-order", action="store_true", help="不导入系列顺序数据")

    def execute(self, args: argparse.Namespace) -> int:
        source_path = Path(SOURCE_CSV)
        if not source_path.exists():
            if self._json_mode:
                return self._respond(False, error=f"源CSV不存在: {SOURCE_CSV}")
            logger.error(f"源CSV不存在: {SOURCE_CSV}")
            return 1

        # 读取迁移模式设置
        config_path = source_path.parent.parent.parent / "config.json"
        migrate_mode = "copy"
        try:
            import json
            cfg_path = get_project_root() / "config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                migrate_mode = cfg.get("project_settings", {}).get("migrate_mode", "copy")
        except Exception:
            pass

        # 加载点赞数据
        likes_data = {}
        if not args.no_likes:
            try:
                likes_path = Path(LIKES_JSON)
                if likes_path.exists():
                    raw = json.loads(likes_path.read_text(encoding="utf-8"))
                    for pixiv_id, info in raw.items():
                        key = (info.get("title", "").strip(), info.get("author", "").strip())
                        likes_data[key] = info.get("like_count", 0)
                    logger.info(f"已加载点赞数据: {len(likes_data)} 条")
            except Exception as e:
                logger.warning(f"加载点赞数据失败: {e}")

        # 加载系列顺序数据
        series_order = {}
        if not args.no_series_order:
            try:
                so_path = Path(SERIES_ORDER_JSON)
                if so_path.exists():
                    raw = json.loads(so_path.read_text(encoding="utf-8"))
                    for series_name, urls in raw.items():
                        for idx, url in enumerate(urls):
                            import re
                            m = re.search(r'[?&]id=(\d+)', url)
                            if m:
                                pixiv_id = m.group(1)
                                series_order[pixiv_id] = (series_name, idx + 1)
                    logger.info(f"已加载系列顺序数据: {len(series_order)} 条")
            except Exception as e:
                logger.warning(f"加载系列顺序数据失败: {e}")

        import csv
        rows = []
        with open(source_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        # 按作者筛选
        if args.author:
            rows = [r for r in rows if r.get("作者", "") == args.author]
            if not rows:
                if self._json_mode:
                    return self._respond(True, data={"total": 0, "message": f"未找到作者: {args.author}"})
                logger.info(f"未找到作者: {args.author}")
                return 0

        # 按系列筛选
        if args.series:
            filtered = []
            for r in rows:
                csv_series = r.get("系列", "").strip()
                if csv_series == args.series:
                    filtered.append(r)
                    continue
                source = r.get("来源", "")
                pixiv_id_match = re.search(r'[?&]id=(\d+)', source)
                if pixiv_id_match:
                    pixiv_id = pixiv_id_match.group(1)
                    if pixiv_id in series_order:
                        so_series, _ = series_order[pixiv_id]
                        if so_series == args.series:
                            filtered.append(r)
                            continue
                # 模糊匹配
                if args.series.lower() in csv_series.lower():
                    filtered.append(r)
            rows = filtered
            if not rows:
                if self._json_mode:
                    return self._respond(True, data={"total": 0, "message": f"未找到系列: {args.series}"})
                logger.info(f"未找到系列: {args.series}")
                return 0

        # 按系列+顺序排序，使ID的work_id反映实际顺序
        # 无顺序的作品排在前面（按导入时间），有顺序的排后面
        if not args.no_series_order:
            def _sort_key(row):
                author = row.get("作者", "")
                csv_series = row.get("系列", "").strip()
                source = row.get("来源", "")
                import_time = row.get("导入时间", "")
                
                # 确定该行属于哪个系列
                detected_series = csv_series
                has_order = False
                order_val = 99999
                
                pixiv_id_match = re.search(r'[?&]id=(\d+)', source)
                if pixiv_id_match:
                    pixiv_id = pixiv_id_match.group(1)
                    if pixiv_id in series_order:
                        so_series, so_order = series_order[pixiv_id]
                        detected_series = so_series
                        has_order = True
                        order_val = so_order
                
                # 排序：作者 → 系列 → 有无顺序(有顺序=0在前) → 顺序 → 导入时间
                if has_order:
                    return (author, detected_series, 0, order_val, import_time)
                else:
                    return (author, detected_series, 1, 0, import_time)
            rows.sort(key=_sort_key)

        if args.limit > 0:
            rows = rows[:args.limit]

        total = len(rows)
        success = 0
        skipped = 0
        failed = 0
        error_details = []

        bm = BookManager()

        if args.dry_run:
            preview = []
            for i, row in enumerate(rows[:20]):
                fp = Path(row.get("文件路径", ""))
                title = row.get("文件名", "")
                if title:
                    title = Path(title).stem
                preview.append(f"{title} ({row.get('作者', '未知')}) → {'复制' if migrate_mode == 'copy' else '移动'}")
            if self._json_mode:
                return self._respond(True, data={"dry_run": True, "total": total, "preview": preview})
            logger.info(f"迁移预览: 共 {total} 条记录，模式: {migrate_mode}")
            for line in preview:
                logger.info(f"  {line}")
            if total > 20:
                logger.info(f"  ... 还有 {total - 20} 条记录")
            return 0

        import shutil

        logger.info(f"开始迁移，共 {total} 条记录，预计需要一些时间...")

        for i, row in enumerate(rows):
            source_file = Path(row.get("文件路径", ""))
            title = row.get("文件名", "")
            if title:
                title = Path(title).stem
            author = row.get("作者", "佚名")
            series = normalize_series_name(row.get("系列", "") or "")
            tags = row.get("标签", "") or ""
            source = row.get("来源", "") or ""
            md5_old = row.get("MD5", "")

            # 检查文件是否存在
            if not source_file.exists():
                failed += 1
                error_details.append({"title": title, "error": f"文件不存在: {source_file}"})
                continue

            # 检查MD5是否已存在
            import hashlib
            try:
                with open(source_file, 'rb') as f:
                    file_hash = hashlib.md5()
                    for chunk in iter(lambda: f.read(8192), b''):
                        file_hash.update(chunk)
                md5 = file_hash.hexdigest()
            except Exception:
                failed += 1
                error_details.append({"title": title, "error": "无法读取文件"})
                continue

            # 检查是否已有相同MD5的书
            existing = WorkManager.read()
            is_dup = any(r.get("MD5") == md5 for r in existing)
            if is_dup:
                skipped += 1
                continue

            # 查找系列顺序（在生成ID之前）
            pixiv_id_match = re.search(r'[?&]id=(\d+)', source)
            if pixiv_id_match and not args.no_series_order:
                pixiv_id = pixiv_id_match.group(1)
                if pixiv_id in series_order:
                    so_series, so_order = series_order[pixiv_id]
                    if not series:
                        series = so_series

            # 生成新ID和导入目标
            from src.core.registry import generate_id
            from src.core.filetype import determine_file_type
            from src.core.paths import build_import_target
            file_type = determine_file_type(str(source_file))
            book_id = generate_id(file_type, author, series)
            target = build_import_target(source_file, author, series)
            target.parent.mkdir(parents=True, exist_ok=True)

            if target.exists():
                skipped += 1
                continue

            try:
                if migrate_mode == "move":
                    shutil.move(str(source_file), str(target))
                else:
                    shutil.copy2(source_file, target)

                file_size_kb = round(target.stat().st_size / 1024, 2)

                # 检测繁简转换
                from src.core.converter import is_traditional_chinese, convert_to_simplified, convert_file_to_simplified
                from src.core.config import get_convert_setting
                final_title = title
                final_author = author or "佚名"
                final_series = series
                final_tags = tags

                convert_traditional = get_convert_setting()

                if convert_traditional:
                    if is_traditional_chinese(final_title):
                        convert_file_to_simplified(target)
                        final_title = convert_to_simplified(final_title)
                    if is_traditional_chinese(final_author):
                        final_author = convert_to_simplified(final_author)
                    if is_traditional_chinese(final_series):
                        final_series = convert_to_simplified(final_series)
                    if is_traditional_chinese(final_tags):
                        final_tags = convert_to_simplified(final_tags)

                # 查找点赞数据
                like_count = likes_data.get((title.strip(), author.strip()), 0)

                entry = {
                    "ID": book_id,
                    "标题": final_title,
                    "作者": final_author,
                    "系列": final_series,
                    "标签": final_tags,
                    "来源": source,
                    "后缀": target.suffix.lower(),
                    "分类": file_type,
                    "导入时间": row.get("导入时间", ""),
                    "文件大小(KB)": str(file_size_kb),
                    "MD5": md5,
                    "文件路径": str(target.absolute()),
                    "收藏": "否",
                    "评分": "",
                    "简介": "",
                    "点赞": str(like_count) if like_count else "0",
                }
                from src.core.work_repository import append_one
                append_one(entry)
                success += 1
            except Exception as e:
                failed += 1
                error_details.append({"title": title, "error": str(e)})

        if self._json_mode:
            return self._respond(True, data={
                "total": total,
                "imported": success,
                "skipped": skipped,
                "failed": failed,
                "error_details": error_details[:20],
            })

        logger.info(f"迁移完成!")
        logger.info(f"  总记录: {total}")
        logger.info(f"  成功: {success}")
        logger.info(f"  跳过(重复): {skipped}")
        logger.info(f"  失败: {failed}")

        if error_details:
            logger.info("错误详情:")
            for e in error_details[:10]:
                logger.error(f"  {e['title']}: {e['error']}")
            if len(error_details) > 10:
                logger.info(f"  ... 还有 {len(error_details) - 10} 条错误")

        return 0 if failed == 0 else 1
