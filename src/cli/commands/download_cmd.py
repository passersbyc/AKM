import argparse

from src.cli.base import BaseCommand
from src.cli.commands._download_utils import DownloadGroupRunner
from src.core.logging import logger


class DownloadCommand(BaseCommand):
    verb = "download"
    nouns: list[str] = []
    description = "直接下载指定 URL（不经过下载队列）"
    group = "订阅下载"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("url", type=str, help="要下载的 URL～")
        parser.add_argument("--site", "-s", type=str, default=None,
                            help="指定下载源～")
        parser.add_argument("-m", "--mode", type=str, default="both",
                            choices=["both", "meta", "works"],
                            help="下载模式: both(完整)/meta(仅元数据)/works(仅作品文件)～")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        url = args.url
        logger.info(f"下载: {url}")

        runner = DownloadGroupRunner(
            [url], mode=args.mode, site=args.site,
        )
        results = runner.run()

        from src.operations.pull_op import reindex_after_pull
        reindex_after_pull([url])

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
