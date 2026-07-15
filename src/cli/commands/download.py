import argparse
import re
import signal
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Any

from src.cli.core import BaseCommand
from src.cli.downplugin.base import AuthError
from src.cli.downplugin import registry
from src.core.logging import logger
from src.core.download import read_download_json, pop_download_json
from src.core.paths import delete_downloads_file
from src.operations import source_set


def _draw_chart(total_success: int, total_failed: int, total_skipped: int,
                timeline: Any = None) -> None:
    total = total_success + total_failed + total_skipped
    if total == 0:
        return
    try:
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
    except ImportError:
        return

    for name in ["PingFang SC", "Heiti SC", "STHeiti", "SimHei", "Microsoft YaHei", "Noto Sans CJK SC"]:
        available = [f.name for f in fm.fontManager.ttflist]
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    plt.rcParams["axes.unicode_minus"] = False

    has_timeline = timeline and len(timeline) > 1
    ncols = 2 if has_timeline else 1
    fig, axes = plt.subplots(1, ncols, figsize=(6 * ncols, 4.5))
    if not has_timeline:
        axes = [axes]

    ax = axes[0]
    labels = ["成功", "失败", "跳过"]
    values = [total_success, total_failed, total_skipped]
    colors = ["#4caf50", "#f44336", "#ff9800"]
    bars = ax.bar(labels, values, color=colors, edgecolor="white", linewidth=0.8)
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + total * 0.02,
                    f"{val}\n({val / total * 100:.0f}%)", ha="center", va="bottom", fontsize=12)
    ax.set_title(f"下载统计 (共 {total} 个)", fontsize=14, fontweight="bold")
    ax.set_ylabel("数量", fontsize=12)
    ax.set_ylim(0, max(values) * 1.25 if max(values) > 0 else 10)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    if has_timeline:
        ax2 = axes[1]
        times = [t for t, _ in timeline]
        counts = [c for _, c in timeline]
        ax2.plot(times, counts, color="#2196f3", linewidth=1.5, marker=".", markersize=3, alpha=0.8)
        if times[-1] > 0:
            avg_rate = counts[-1] / times[-1]
            ax2.axline((0, 0), slope=avg_rate, color="#ff9800", linestyle="--", linewidth=1,
                        label=f"均速 {avg_rate:.2f} 个/秒")
        ax2.set_xlabel("用时 (秒)", fontsize=12)
        ax2.set_ylabel("累计完成", fontsize=12)
        ax2.set_title("下载速度曲线", fontsize=14, fontweight="bold")
        ax2.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax2.spines["top"].set_visible(False)
        ax2.spines["right"].set_visible(False)
        ax2.legend(fontsize=10)

    plt.tight_layout()
    plt.show()


class DownloadCommand(BaseCommand):
    """
    下载命令实现类。支持 Pixiv 及未来扩展的站点。
    """

    def __init__(self) -> None:
        super().__init__()
        self.args: Optional[argparse.Namespace] = None

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

    # ── properties ───────────────────────────────────────

    @property
    def name(self) -> str:
        return "download"

    @property
    def description(self) -> str:
        return "下载资源、导入作品"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "urls",
            type=str,
            nargs='*',
            help="要下载的资源网址（--pull 模式下可省略）"
        )
        parser.add_argument(
            "--site", "-s",
            type=str,
            default=None,
            help=f"指定下载源 (可用: {', '.join(registry.list_sites())})"
        )
        parser.add_argument(
            "-c", "--chart",
            action="store_true",
            help="下载完成后显示统计图表"
        )
        parser.add_argument(
            "-m", "--mode",
            type=str, default="both",
            choices=["both", "meta", "works"],
            help="下载模式: both(默认,完整下载), meta(仅元数据), works(仅作品文件)"
        )
        parser.add_argument(
            "-p", "--pull",
            action="store_true",
            help="从下载队列中读取待下载作品"
        )
        parser.add_argument(
            "--pull-base",
            action="store_true",
            help="同 --pull，但遇到旧库已有文件时复用文件仅爬取元数据"
        )

    def execute(self, args: argparse.Namespace) -> int:
        self.args = args
        return self._execute_default(args)

    def _execute_default(self, args: argparse.Namespace) -> int:
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

        start_time = time.monotonic()
        total_success = 0
        total_failed = 0
        total_skipped = 0
        all_timeline = []
        lock = threading.Lock()

        # 按下载器分组
        groups: dict[str, list[str]] = defaultdict(list)
        unsupported: list[str] = []
        for u in urls:
            cls = registry.resolve(u, site=args.site)
            if not cls:
                unsupported.append(u)
                continue
            groups[cls.name].append(u)

        for u in unsupported:
            logger.warning(f"不支持的链接: {u}")
            total_failed += 1

        def _process_group(site_name, site_urls, _dl_ref):
            """在线程中处理一个站点的所有 URL"""
            cls = registry.resolve(site_urls[0], site=args.site)
            if not cls:
                return {"success": 0, "failed": len(site_urls), "skipped": 0, "_timeline": None, "_latest_tl": None}

            downloader = cls()
            if pull_base_mapping:
                downloader.set_pull_base_mapping(pull_base_mapping)
            _dl_ref["instance"] = downloader
            group_stats = {"success": 0, "failed": 0, "skipped": 0, "_timeline": None, "_latest_tl": None}

            # 用 expand_urls 将复合链接展开为单作品链接
            if downloader.supports_expand:
                work_urls = downloader.expand_urls(site_urls)
                logger.info(f"[{site_name}] {len(site_urls)} 个链接 → 展开为 {len(work_urls)} 个作品")
            else:
                work_urls = site_urls

            try:
                stats = downloader.process_url(work_urls, mode=args.mode)
            except AuthError:
                raise
            except KeyboardInterrupt:
                downloader.stop_event.set()
                raise
            except Exception as e:
                logger.error(f"[{site_name}] 处理失败: {e}")
                group_stats["failed"] += len(work_urls)
                return group_stats

            group_stats["success"] = stats.get("success", 0)
            group_stats["failed"] = stats.get("failed", 0)
            group_stats["skipped"] = stats.get("skipped", 0)
            if stats.get("_timeline"):
                group_stats["_latest_tl"] = stats["_timeline"]
            return group_stats

        try:
            old_handler = signal.getsignal(signal.SIGINT)
            downloaders = {}  # {name: {"instance": downloader}}
            executor = None

            def _sigint_handler(signum, frame):
                for d in downloaders.values():
                    inst = d.get("instance")
                    if inst:
                        inst.stop()
                if executor:
                    executor.shutdown(wait=False, cancel_futures=True)

            signal.signal(signal.SIGINT, _sigint_handler)

            with ThreadPoolExecutor(max_workers=max(len(groups), 1)) as executor:
                futures = {
                    executor.submit(_process_group, name, urls, downloaders.setdefault(name, {})): name
                    for name, urls in groups.items()
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        stats = future.result()
                    except KeyboardInterrupt:
                        logger.info("用户取消下载")
                        return 130
                    except AuthError:
                        raise
                    except Exception as e:
                        logger.error(f"[{name}] 站点处理异常: {e}")
                        continue
                    with lock:
                        total_success += stats.get("success", 0)
                        total_failed += stats.get("failed", 0)
                        total_skipped += stats.get("skipped", 0)
                        tl = stats.get("_latest_tl")
                        if tl:
                            base = sum(t for t, _ in all_timeline[-1:]) if all_timeline else 0
                            base_count = all_timeline[-1][1] if all_timeline else 0
                            for elapsed, count in tl:
                                all_timeline.append((base + elapsed, base_count + count))

        except (KeyboardInterrupt, AuthError):
            if isinstance(sys.exc_info()[1], KeyboardInterrupt):
                return 130
            raise
        finally:
            signal.signal(signal.SIGINT, old_handler)

        delete_downloads_file()

        if pull_urls:
            self._purge_download_json(pull_urls)

        total_processed = total_success + total_failed + total_skipped
        elapsed = time.monotonic() - start_time

        summary_line = f"总计处理: {total_processed} | 成功: {total_success} | 失败: {total_failed} | 跳过: {total_skipped} | 耗时: {elapsed:.1f} 秒"
        logger.info(summary_line)

        if getattr(args, "chart", False) and total_processed > 0:
            _draw_chart(total_success, total_failed, total_skipped, all_timeline)

        return self._respond(
            total_failed == 0,
            data={
                "total": total_processed,
                "success": total_success,
                "failed": total_failed,
                "skipped": total_skipped,
                "elapsed": round(elapsed, 1),
            },
        )

    @staticmethod
    def _get_pull_base_csv_path() -> str:
        from src.core.config import load_config
        cfg = load_config()
        return cfg.get("project_settings", {}).get("pull_base_csv", "")


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
                mapping[source] = {
                    "file_path": file_path,
                }
    return mapping
