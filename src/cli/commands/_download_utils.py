"""下载 CLI 表现层包装 —— 在下载调度核心（downloader/runner.py）之上叠加：
  - 键盘监听（p 暂停 / o 继续 / c 取消）
  - SIGINT 信号处理（第一次暂停，第二次强制 shutdown）
  - matplotlib 统计图表

业务调度逻辑（分组/并发/收集结果）已下沉到 src/downloader/runner.py，
WebUI 可直接调 run_download_groups 而不碰本模块的 CLI 表现层。
"""
import signal
import sys
import threading
import select
import termios
import tty
from typing import Optional

from src.downloader.context import DownloadControl
from src.downloader.runner import run_download_groups


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
                ctrl.request_cancel()
                sys.stderr.write("\r⏹ 退出中...\n")
                sys.stderr.flush()
                break
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


class DownloadGroupRunner:
    """CLI 下载运行器：调度核心 + 键盘/信号/图表包装。

    接口保持不变（pull_cmd 零改动），run() 内部调 run_download_groups 核心。
    """

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
        # 键盘监听线程（CLI 表现层）
        listener = threading.Thread(target=_key_listener, args=(self.ctrl,),
                                     daemon=True)
        listener.start()

        # SIGINT 处理（CLI 表现层）：第一次暂停，第二次强制 shutdown executor
        executor_ref: list[Optional[object]] = [None]

        def _sigint_handler(signum, frame):
            self.ctrl.sigint_count += 1
            if self.ctrl.sigint_count == 1:
                self.ctrl.pause.set()
                sys.stderr.write("\r⏸ 正在暂停... (再按 Ctrl+C 强制退出)\n")
                sys.stderr.flush()
            else:
                self.ctrl.request_cancel()
                if executor_ref[0]:
                    executor_ref[0].shutdown(wait=False,
                                              cancel_futures=True)

        old_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _sigint_handler)

        def _hook(executor):
            executor_ref[0] = executor

        try:
            # 调度核心（业务逻辑，不含 CLI 表现层）
            self.results = run_download_groups(
                self.urls,
                mode=self.mode,
                site=self.site,
                pull_base_mapping=self.pull_base_mapping,
                ctrl=self.ctrl,
                executor_hook=_hook,
            )
        finally:
            signal.signal(signal.SIGINT, old_handler)

        self.ctrl.cancel.set()
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
