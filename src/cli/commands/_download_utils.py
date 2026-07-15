import signal
import sys
import time
import threading
import select
import termios
import tty
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from src.cli.downplugin import registry
from src.cli.downplugin.base import AuthError
from src.cli.downplugin.context import DownloadControl
from src.core.logging import logger


def _key_listener(ctrl: DownloadControl):
    fd = sys.stdin.fileno()
    try:
        old = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    except (termios.error, OSError):
        return

    try:
        while not ctrl.cancelled:
            r, _, _ = select.select([sys.stdin], [], [], 0.5)
            if not r:
                continue
            key = sys.stdin.read(1).lower()
            if key == 'p' and not ctrl.paused:
                ctrl.pause.set()
                sys.stderr.write("\r⏸ 正在暂停...\n")
                sys.stderr.flush()
            elif key == 'o' and ctrl.paused:
                ctrl.pause.clear()
                sys.stderr.write("\r▶ 已继续\n")
                sys.stderr.flush()
            elif key == 'c':
                ctrl.pause.set()
                ctrl.cancel.set()
                sys.stderr.write("\r⏹ 退出中...\n")
                sys.stderr.flush()
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class DownloadGroupRunner:
    def __init__(self, urls: list[str], *, mode: str = "both",
                 site: Optional[str] = None,
                 pull_base_mapping: Optional[dict] = None,
                 show_chart: bool = False):
        self.urls = urls
        self.mode = mode
        self.site = site
        self.pull_base_mapping = pull_base_mapping or {}
        self.show_chart = show_chart
        self.ctrl = DownloadControl()
        self.results = {"success": 0, "failed": 0, "skipped": 0,
                         "total": 0, "elapsed": 0.0, "timeline": [],
                         "cancelled": False}

    def run(self) -> dict:
        groups: dict[str, list[str]] = defaultdict(list)
        unsupported: list[str] = []
        for u in self.urls:
            cls = registry.resolve(u, site=self.site)
            if not cls:
                unsupported.append(u)
                continue
            groups[cls.name].append(u)

        for u in unsupported:
            logger.warning(f"不支持的链接: {u}")
            self.results["failed"] += 1

        if not groups:
            return self.results

        listener = threading.Thread(target=_key_listener, args=(self.ctrl,),
                                     daemon=True)
        listener.start()

        start_time = time.monotonic()
        lock = threading.Lock()
        downloaders: dict[str, dict] = {}
        executor_ref: list[Optional[ThreadPoolExecutor]] = [None]

        try:
            old_handler = signal.getsignal(signal.SIGINT)

            def _sigint_handler(signum, frame):
                self.ctrl.sigint_count += 1
                if self.ctrl.sigint_count == 1:
                    self.ctrl.pause.set()
                    sys.stderr.write("\r⏸ 正在暂停... (再按 Ctrl+C 强制退出)\n")
                    sys.stderr.flush()
                else:
                    self.ctrl.cancel.set()
                    for d in downloaders.values():
                        inst = d.get("instance")
                        if inst:
                            inst.stop()
                    if executor_ref[0]:
                        executor_ref[0].shutdown(wait=False,
                                                  cancel_futures=True)

            signal.signal(signal.SIGINT, _sigint_handler)

            def _process_group(site_name, site_urls, _dl_ref):
                cls = registry.resolve(site_urls[0], site=self.site)
                if not cls:
                    return {"success": 0, "failed": len(site_urls),
                            "skipped": 0, "_timeline": None}
                downloader = cls()
                downloader.set_download_control(self.ctrl)
                if self.pull_base_mapping:
                    downloader.set_pull_base_mapping(self.pull_base_mapping)
                _dl_ref["instance"] = downloader
                group_stats = {"success": 0, "failed": 0, "skipped": 0,
                                "_timeline": None}

                if downloader.supports_expand:
                    work_urls = downloader.expand_urls(site_urls)
                    logger.info(f"[{site_name}] {len(site_urls)} 个链接 → "
                                 f"展开为 {len(work_urls)} 个作品")
                else:
                    work_urls = site_urls

                try:
                    stats = downloader.process_url(work_urls, mode=self.mode)
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
                    group_stats["_timeline"] = stats["_timeline"]
                return group_stats

            with ThreadPoolExecutor(max_workers=max(len(groups), 1)) as executor:
                executor_ref[0] = executor
                futures = {
                    executor.submit(
                        _process_group, name, urls,
                        downloaders.setdefault(name, {})
                    ): name
                    for name, urls in groups.items()
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        stats = future.result()
                    except KeyboardInterrupt:
                        logger.info("用户取消下载")
                        self.results["cancelled"] = True
                        break
                    except AuthError:
                        raise
                    except Exception as e:
                        logger.error(f"[{name}] 站点处理异常: {e}")
                        continue
                    with lock:
                        self.results["success"] += stats.get("success", 0)
                        self.results["failed"] += stats.get("failed", 0)
                        self.results["skipped"] += stats.get("skipped", 0)
                        tl = stats.get("_timeline")
                        if tl:
                            timeline = self.results["timeline"]
                            base = (sum(t for t, _ in timeline[-1:])
                                    if timeline else 0)
                            base_count = timeline[-1][1] if timeline else 0
                            for elapsed, count in tl:
                                timeline.append(
                                    (base + elapsed, base_count + count))

        except (KeyboardInterrupt, AuthError):
            if isinstance(sys.exc_info()[1], KeyboardInterrupt):
                self.results["cancelled"] = True
            else:
                raise
        finally:
            signal.signal(signal.SIGINT, old_handler)

        self.results["total"] = (self.results["success"] +
                                  self.results["failed"] +
                                  self.results["skipped"])
        self.results["elapsed"] = round(time.monotonic() - start_time, 1)

        listener.join(timeout=2)

        if self.show_chart and self.results["total"] > 0:
            _draw_chart(self.results["success"], self.results["failed"],
                        self.results["skipped"], self.results["timeline"])

        return self.results


def _draw_chart(total_success, total_failed, total_skipped,
                timeline=None) -> None:
    total = total_success + total_failed + total_skipped
    if total == 0:
        return
    try:
        import matplotlib.pyplot as plt
        import matplotlib.font_manager as fm
    except ImportError:
        return

    for name in ["PingFang SC", "Heiti SC", "STHeiti", "SimHei",
                 "Microsoft YaHei", "Noto Sans CJK SC"]:
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
    bars = ax.bar(labels, values, color=colors, edgecolor="white",
                  linewidth=0.8)
    for bar, val in zip(bars, values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + total * 0.02,
                    f"{val}\n({val / total * 100:.0f}%)",
                    ha="center", va="bottom", fontsize=12)
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
        ax2.plot(times, counts, color="#2196f3", linewidth=1.5,
                 marker=".", markersize=3, alpha=0.8)
        if times[-1] > 0:
            avg_rate = counts[-1] / times[-1]
            ax2.axline((0, 0), slope=avg_rate, color="#ff9800",
                       linestyle="--", linewidth=1,
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
