import argparse
import time
from collections import defaultdict

from src.cli.base import BaseCommand
from src.cli.downplugin import registry
from src.cli.commands._download_utils import DownloadGroupRunner
from src.core.download import read_download_json, _write_download_json
from src.core.logging import logger
from src.core.paths import delete_downloads_file
from src.operations import source_set


class PullCommand(BaseCommand):
    verb = "pull"
    nouns: list[str] = []
    description = "拉取下载队列中的待下载作品并入库"

    def __init__(self) -> None:
        super().__init__()
        self.args: argparse.Namespace | None = None

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--site", "-s", type=str, default=None,
                            help=f"指定下载源 (可用: {', '.join(registry.list_sites())})")
        parser.add_argument("-c", "--chart", action="store_true",
                            help="下载完成后显示统计图表")
        parser.add_argument("-m", "--mode", type=str, default="both",
                            choices=["both", "meta", "works"],
                            help="下载模式: both(完整)/meta(仅元数据)/works(仅作品文件)")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        self.args = args
        data = read_download_json()
        all_urls: list[str] = []
        for entry in data.get("works", []):
            u = entry.get("url", "").strip()
            if u and u not in all_urls:
                all_urls.append(u)

        if not all_urls:
            self.output.info("下载队列为空，先用 follow source 同步收集新作再 pull")
            return 0

        in_library = source_set()
        pending_urls: list[str] = []
        skipped_in_library = 0
        for u in all_urls:
            if u in in_library:
                skipped_in_library += 1
            else:
                pending_urls.append(u)

        if skipped_in_library > 0:
            remaining = [e for e in data.get("works", [])
                         if e.get("url", "").strip() not in in_library]
            data["works"] = remaining
            _write_download_json(data)
            logger.info(f"已清理队列: {skipped_in_library} 个已入库")

        if not pending_urls:
            self.output.info("队列中的作品均已入库，无需下载")
            return 0

        logger.info(f"从下载队列拉取 {len(pending_urls)} 个作品"
                     f"（跳过 {skipped_in_library} 个已入库）")

        runner = DownloadGroupRunner(
            pending_urls,
            mode=args.mode,
            site=args.site,
            show_chart=getattr(args, "chart", False),
        )
        results = runner.run()

        delete_downloads_file()

        summary = (f"总计处理: {results['total']}"
                    f" | 成功: {results['success']}"
                    f" | 失败: {results['failed']}"
                    f" | 跳过: {results['skipped']}"
                    f" | 耗时: {results['elapsed']} 秒")
        logger.info(summary)

        return self.output.result(
            results["failed"] == 0,
            data={
                "total": results["total"],
                "success": results["success"],
                "failed": results["failed"],
                "skipped": results["skipped"],
                "elapsed": results["elapsed"],
            },
        )
