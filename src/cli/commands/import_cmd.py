import argparse
from pathlib import Path

from src.cli.base import BaseCommand
from src.core.logging import logger
from src.sdk import batch_import_cdbook, batch_import_folder, import_files_batch


class ImportCommand(BaseCommand):
    verb = "import"
    nouns: list[str] = []
    description = "将文件导入到作品库中（自动识别单文件 / cdbook 目录 / 普通文件夹）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("files", type=str, nargs="+", help="要导入的文件路径")
        parser.add_argument("-a", "--author", type=str, default="", help="作者名称")
        parser.add_argument("-s", "--series", type=str, default="", help="系列名称")
        parser.add_argument("-t", "--tags", type=str, default="", help="标签（逗号分隔）")
        parser.add_argument("-o", "--source", type=str, default="", help="来源URL")
        parser.add_argument("-f", "--favorite", action="store_true", help="标记为收藏")
        parser.add_argument("-r", "--rating", type=float, default=0.0, help="评分 (0-10，支持小数)")
        parser.add_argument("-d", "--description", type=str, default="", help="简介")
        parser.add_argument("--target-format", type=str, default="epub",
                            choices=["epub", "txt"], help="doc/docx转换的目标格式（默认epub）")
        parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际导入")
        parser.add_argument("--limit", type=int, default=0, help="限制导入文件数量（测试用）")
        parser.add_argument("-y", "--yes", action="store_true", help="跳过确认提示")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        rating = args.rating
        if not (0.0 <= rating <= 10.0):
            return self.output.result(False, error="评分必须在 0-10 之间")

        paths = [Path(f) for f in args.files]
        cdbook_dirs = [p for p in paths if p.is_dir() and p.name.lower() == "cdbook"]
        non_cdbook_dirs = [p for p in paths if p.is_dir() and p.name.lower() != "cdbook"]
        files = [p for p in paths if p.is_file()]

        if non_cdbook_dirs:
            if cdbook_dirs or files or len(non_cdbook_dirs) > 1:
                return self.output.result(False, error="文件夹导入不能与其他路径混合，且一次只能一个")
            folder = str(non_cdbook_dirs[0])
            logger.info(f"检测到文件夹，作者: {non_cdbook_dirs[0].name}，进入批量导入模式...")
            return self._report_batch(
                batch_import_folder(
                    directory=folder, dry_run=args.dry_run, limit=args.limit,
                    target_format=args.target_format, tags=args.tags, source=args.source,
                ), args
            )

        if cdbook_dirs:
            if len(cdbook_dirs) > 1 or files:
                return self.output.result(False, error="cdbook 目录导入不能与其他路径混合，且一次只能一个")
            logger.info("检测到 cdbook 目录，进入批量导入模式...")
            return self._report_batch(
                batch_import_cdbook(directory=str(cdbook_dirs[0]),
                                    dry_run=args.dry_run, limit=args.limit),
                args,
            )

        if not files:
            return self.output.result(False, error="未找到有效的文件或 cdbook 目录")

        results = import_files_batch(
            files=[str(f) for f in files], author=args.author or "佚名", series=args.series,
            tags=args.tags, source=args.source, favorited=args.favorite,
            rating=rating, description=args.description, target_format=args.target_format,
        )
        if self.output.json_mode:
            output = [{
                "success": r.success, "file_name": r.file_name, "book_id": r.book_id,
                "file_type": r.file_type, "file_size_kb": r.file_size_kb,
                "storage_path": r.storage_path, "md5": r.md5,
                "error": r.error, "duplicate_of": r.duplicate_of,
            } for r in results]
            imported = sum(1 for r in results if r.success)
            return self.output.result(True, data={"total": len(results), "imported": imported, "results": output})

        success = skip = fail = 0
        for r in results:
            if r.success:
                extra = []
                if args.favorite:
                    extra.append("收藏")
                if rating:
                    extra.append(f"{rating}分")
                tail = f" ({', '.join(extra)})" if extra else ""
                logger.info(f"导入成功: {r.file_name} ({r.file_type}){tail}")
                self.output.info(f"  ID: [cyan]{r.book_id}[/cyan]")
                success += 1
            elif r.duplicate_of:
                logger.info(f"MD5重复，已存在: {r.duplicate_of}，跳过")
                skip += 1
            else:
                logger.error(f"导入失败: {r.file_name} | {r.error}")
                fail += 1
        logger.info(f"导入完成。成功: {success} | 跳过: {skip} | 失败: {fail}")
        return 0 if fail == 0 else 1

    def _report_batch(self, result: dict, args: argparse.Namespace) -> int:
        if self.output.json_mode:
            return self.output.result(True, data=result)
        if args.dry_run:
            logger.info(f"预览模式: 共 {result['total_files']} 个文件, {result['series_count']} 个系列")
            for line in result.get("preview", []):
                logger.info(f"  {line}")
            if result["total_files"] > 50:
                logger.info(f"  ... 还有 {result['total_files'] - 50} 个文件")
            return 0
        logger.info("批量导入完成!")
        logger.info(f"  总文件: {result['total']}")
        logger.info(f"  导入成功: {result['imported']}")
        logger.info(f"  跳过(重复): {result['skipped']}")
        logger.info(f"  失败: {result['errors']}")
        ids = result.get("imported_ids", [])
        if ids:
            self.output.info(f"  最新ID: [cyan]{', '.join(ids)}[/cyan]")
        if result.get("error_details"):
            logger.info("错误详情:")
            for e in result["error_details"]:
                logger.error(f"  {e['file']}: {e['error']}")
        return 0 if result["errors"] == 0 else 1
