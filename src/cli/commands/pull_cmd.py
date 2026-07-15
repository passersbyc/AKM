import argparse
import signal
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.cli.base import BaseCommand
from src.cli.downplugin.base import AuthError
from src.cli.downplugin import registry
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

        # 过滤已入库的 URL（source 已存在于 works 表中）
        in_library = source_set()
        pending_urls: list[str] = []
        skipped_in_library = 0
        for u in all_urls:
            if u in in_library:
                skipped_in_library += 1
            else:
                pending_urls.append(u)

        # 清理队列中已入库的条目
        if skipped_in_library > 0:
            remaining = [e for e in data.get("works", []) if e.get("url", "").strip() not in in_library]
            data["works"] = remaining
            _write_download_json(data)
            logger.info(f"已清理队列: {skipped_in_library} 个已入库")

        if not pending_urls:
            self.output.info("队列中的作品均已入库，无需下载")
            return 0

        logger.info(f"从下载队列拉取 {len(pending_urls)} 个作品（跳过 {skipped_in_library} 个已入库）")
        urls = pending_urls

        start_time = time.monotonic()
        total_success = 0
        total_failed = 0
        total_skipped = 0
        all_timeline: list[tuple[float, int]] = []
        lock = threading.Lock()

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
            cls = registry.resolve(site_urls[0], site=args.site)
            if not cls:
                return {"success": 0, "failed": len(site_urls), "skipped": 0,
                        "_timeline": None, "_latest_tl": None}
            downloader = cls()
            _dl_ref["instance"] = downloader
            group_stats = {"success": 0, "failed": 0, "skipped": 0,
                           "_timeline": None, "_latest_tl": None}

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
            downloaders: dict[str, dict] = {}
            executor_ref = [None]

            def _sigint_handler(signum, frame):
                for d in downloaders.values():
                    inst = d.get("instance")
                    if inst:
                        inst.stop()
                if executor_ref[0]:
                    executor_ref[0].shutdown(wait=False, cancel_futures=True)

            signal.signal(signal.SIGINT, _sigint_handler)

            with ThreadPoolExecutor(max_workers=max(len(groups), 1)) as executor:
                executor_ref[0] = executor
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
            import sys
            if isinstance(sys.exc_info()[1], KeyboardInterrupt):
                return 130
            raise
        finally:
            signal.signal(signal.SIGINT, old_handler)

        delete_downloads_file()

        total_processed = total_success + total_failed + total_skipped
        elapsed = time.monotonic() - start_time

        summary = f"总计处理: {total_processed} | 成功: {total_success} | 失败: {total_failed} | 跳过: {total_skipped} | 耗时: {elapsed:.1f} 秒"
        logger.info(summary)

        if getattr(args, "chart", False) and total_processed > 0:
            self._draw_chart(total_success, total_failed, total_skipped, all_timeline)

        return self.output.result(
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
    def _draw_chart(total_success, total_failed, total_skipped, timeline=None) -> None:
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
