import argparse
from typing import List, Optional

from src.cli.core import BaseCommand
from src.cli.downplugin import registry
from src.cli.commands._download_utils import DownloadGroupRunner
from src.core.logging import logger
from src.core.download import read_download_json
from src.core.paths import delete_downloads_file
from src.operations import source_set


class DownloadCommand(BaseCommand):
    name = "download"
    description = "下载资源、导入作品"

    def __init__(self) -> None:
        super().__init__()
        self.args: Optional[argparse.Namespace] = None

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "urls", type=str, nargs='*',
            help="要下载的资源网址（--pull 模式下可省略）")
        parser.add_argument(
            "--site", "-s", type=str, default=None,
            help=f"指定下载源 (可用: {', '.join(registry.list_sites())})")
        parser.add_argument(
            "-c", "--chart", action="store_true",
            help="下载完成后显示统计图表")
        parser.add_argument(
            "-m", "--mode", type=str, default="both",
            choices=["both", "meta", "works"],
            help="下载模式: both(默认,完整下载), meta(仅元数据), works(仅作品文件)")
        parser.add_argument(
            "-p", "--pull", action="store_true",
            help="从下载队列中读取待下载作品")
        parser.add_argument(
            "--pull-base", action="store_true",
            help="同 --pull，但遇到旧库已有文件时复用文件仅爬取元数据")

    def execute(self, args: argparse.Namespace) -> int:
        self.args = args
        urls: List[str] = [u.strip() for u in (args.urls or []) if u.strip()]
        pull_urls: list[str] = []
        pull_base_mapping: dict = {}

        if args.pull or args.pull_base:
            data = read_download_json()
            for entry in data.get("works", []):
                u = entry.get("url", "").strip()
                if u and u not in urls:
                    pull_urls.append(u)
            if pull_urls:
                logger.info(f"从下载中转拉取 {len(pull_urls)} 个作品")
            elif not urls:
                logger.info("下载中转已空，先用 source sync --all 收集新作再 pull")
                return 0

        if args.pull_base:
            csv_path = self._get_pull_base_csv_path()
            if not csv_path:
                logger.error("请先设置旧库 CSV 路径: akm settings set pull_base_csv <path>")
                return 1
            pull_base_mapping = _load_pull_base_csv(csv_path)
            logger.info(f"旧库映射: {len(pull_base_mapping)} 条来源记录")

        urls = urls + pull_urls

        if not urls:
            logger.warning("没有可下载的链接")
            return 1

        logger.info(f"收到 {len(urls)} 个传送请求，准备出发！")

        runner = DownloadGroupRunner(
            urls,
            mode=args.mode,
            site=args.site,
            pull_base_mapping=pull_base_mapping,
            show_chart=getattr(args, "chart", False),
        )
        results = runner.run()

        delete_downloads_file()

        if pull_urls:
            self._purge_download_json(pull_urls)

        summary = (f"总计处理: {results['total']}"
                    f" | 成功: {results['success']}"
                    f" | 失败: {results['failed']}"
                    f" | 跳过: {results['skipped']}"
                    f" | 耗时: {results['elapsed']} 秒")
        logger.info(summary)

        return self._respond(
            results["failed"] == 0,
            data={
                "total": results["total"],
                "success": results["success"],
                "failed": results["failed"],
                "skipped": results["skipped"],
                "elapsed": results["elapsed"],
            },
        )

    def _purge_download_json(self, urls: list[str]) -> None:
        from src.core.download import read_download_json, _write_download_json
        in_manifest = source_set()
        data = read_download_json()
        removed = 0
        remaining = []
        for entry in data.get("works", []):
            if entry.get("url", "") in in_manifest:
                removed += 1
            else:
                remaining.append(entry)
        if removed:
            data["works"] = remaining
            _write_download_json(data)
            logger.info(f"已清理下载中转: {removed} 个已入库")

    @staticmethod
    def _get_pull_base_csv_path() -> str:
        from src.core.config import load_config
        cfg = load_config()
        return cfg.get("project_settings", {}).get("pull_base_csv", "")

    @staticmethod
    def _respond(ok, data=None):
        return 0 if ok else 1


def _load_pull_base_csv(csv_path: str) -> dict[str, dict]:
    import csv
    from pathlib import Path
    p = Path(csv_path)
    if not p.exists():
        return {}
    mapping: dict[str, dict] = {}
    with open(p, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            source = (row.get("来源", "") or "").strip()
            file_path = (row.get("文件路径", "") or "").strip()
            if source and file_path:
                mapping[source] = {"file_path": file_path}
    return mapping
