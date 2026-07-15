import argparse
from pathlib import Path
from src.cli.core import BaseCommand
from src.core.logging import logger
from src.sdk import batch_import_cdbook
from rich.markup import escape as escape_markup


class BatchImportCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "batch-import"

    @property
    def description(self) -> str:
        return "批量导入 cdbook 文包目录（自动解析文件名元数据、系列分组、.doc转txt）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("directories", type=str, nargs="+", help="cdbook 文包目录路径（文件夹名必须为 cdbook，大小写不敏感）")
        parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际导入")
        parser.add_argument("--limit", type=int, default=0, help="限制导入文件数量（测试用）")

    def execute(self, args: argparse.Namespace) -> int:
        valid_dirs = []
        for d in args.directories:
            p = Path(d)
            if not p.is_dir():
                if self._json_mode:
                    return self._respond(False, error=f"目录不存在: {d}")
                logger.error(f"目录不存在: {escape_markup(d)}")
                return 1
            if p.name.lower() != "cdbook":
                if self._json_mode:
                    return self._respond(False, error=f"目录名必须为 'cdbook' (大小写不敏感): {d}")
                logger.error(f"目录名必须为 'cdbook' (大小写不敏感): {escape_markup(d)}")
                return 1
            valid_dirs.append(d)

        all_results = []
        for d in valid_dirs:
            result = batch_import_cdbook(
                directory=d,
                dry_run=args.dry_run,
                limit=args.limit,
            )
            result["_directory"] = d
            all_results.append(result)

        if self._json_mode:
            return self._respond(True, data={"directories": all_results})

        total_files = 0
        total_imported = 0
        total_skipped = 0
        total_errors = 0
        total_series = 0

        for result in all_results:
            if not result["success"]:
                logger.error(f"{escape_markup(result['_directory'])}: {result.get('error', '未知错误')}")
                continue

            if args.dry_run:
                dir_name = escape_markup(result['_directory'])
                logger.info(f"【{dir_name}】 预览模式: 共 {result['total_files']} 个文件, {result['series_count']} 个系列")
                for line in result.get("preview", []):
                    logger.info(f"  {escape_markup(line)}")
                if result["total_files"] > 50:
                    logger.info(f"  ... 还有 {result['total_files'] - 50} 个文件")
            else:
                dir_name = escape_markup(result['_directory'])
                logger.info(f"【{dir_name}】 批量导入完成!")
                logger.info(f"  总文件: {result['total']}")
                logger.info(f"  导入成功: {result['imported']}")
                logger.info(f"  跳过(重复): {result['skipped']}")
                logger.info(f"  失败: {result['errors']}")
                logger.info(f"  检测到系列: {result['series_count']}")
                ids = result.get("imported_ids", [])
                if ids:
                    ids_str = ", ".join(ids)
                    self._print(f"  最新ID: [cyan]{ids_str}[/cyan]")

                total_files += result.get("total", 0)
                total_imported += result.get("imported", 0)
                total_skipped += result.get("skipped", 0)
                total_errors += result.get("errors", 0)
                total_series += result.get("series_count", 0)

                if result.get("error_details"):
                    logger.info("错误详情:")
                    for e in result["error_details"]:
                        logger.error(f"  {escape_markup(e['file'])}: {escape_markup(e['error'])}")

        if args.dry_run:
            return 0

        logger.info(f"总计: 文件 {total_files} | 导入 {total_imported} | 跳过 {total_skipped} | 失败 {total_errors} | 系列 {total_series}")
        return 0 if total_errors == 0 else 1
