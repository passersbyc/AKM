"""统一进度条显示 — rich 驱动。

单行紧凑布局（TTY 动画 / 非终端自动禁用渲染），适配 60+ 列窄终端：
    (◕‿◕) 同步检查  ━━━━━━━━━━  164/175  [0:00:11]  14.8个/s  成功164 失败0 跳过0

- 描述 + 进度条 + 完成数/总数 + 耗时 + 速率 + 成功/失败/跳过计数，一行排布
- 单行布局避免多行进度在窄终端/动画刷新时的换行与错位问题
- 暂停/取消等状态通过动态 description 表达
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.text import Text

# 进度条统一输出到 stderr（与日志同侧，不污染 stdout 的 --json 输出）
_console = Console(stderr=True)


class CountsColumn(ProgressColumn):
    """成功/失败/跳过 三色计数列，读取外部 counts dict，紧凑格式。"""

    def __init__(self, counts: dict, console: Console):
        super().__init__()
        self.counts = counts
        self._console = console

    def render(self, task) -> Text:
        c = self.counts
        t = Text()
        t.append(f"  成功{c.get('success', 0)}", style="green")
        t.append(f"  失败{c.get('failed', 0)}", style="red")
        t.append(f"  跳过{c.get('skipped', 0)}", style="yellow")
        return t


class RateColumn(ProgressColumn):
    """完成速率列（基于任务行自身的 completed/elapsed）。

    速率上限 999：刚开始时 elapsed≈0 会算出天文数字，限宽防止把行撑爆。
    """

    def render(self, task) -> Text:
        if task.elapsed <= 0 or task.completed <= 0:
            return Text("")
        rate = min(task.completed / task.elapsed, 999.0)
        return Text(f"  {rate:.1f}个/s", style="cyan")


def make_progress(counts: dict, desc: str = "进度",
                  total: int = 1) -> tuple[Progress, int, None]:
    """创建单行进度条，返回 (progress, 主行task_id, None)。

    返回的第三个值保持 None 以兼容旧两行式调用方（advance 会忽略）。
    非终端环境（管道/重定向/后台）自动禁用渲染，不产生噪声。
    """
    progress = Progress(
        TextColumn("[bold magenta]{task.description}[/bold magenta]",
                   justify="left"),
        BarColumn(bar_width=8, complete_style="magenta",
                  finished_style="green"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        RateColumn(),
        CountsColumn(counts, _console),
        console=_console,
        disable=not _console.is_terminal,
    )
    main_id = progress.add_task(description=f"(◕‿◕) {desc}", total=total)
    return progress, main_id, None


def advance(progress: Progress, main_id: int, counts_id, n: int = 1) -> None:
    """推进进度条（兼容旧 counts_id 参数，单行布局下忽略）。"""
    progress.update(main_id, advance=n)


@contextmanager
def suppress_console_logging():
    """进度条动画期间静默控制台日志（仍完整写入文件日志）。

    控制台 RichHandler 与进度条同用 stderr 流，下载过程中的日志输出
    会与进度条动画抢占光标导致行错位。进度结束后恢复。
    """
    from src.core.logging import _console_handlers

    if not _console_handlers:
        yield
        return
    old_levels = [h.level for h in _console_handlers]
    for h in _console_handlers:
        h.setLevel(logging.CRITICAL + 1)
    try:
        yield
    finally:
        for h, lvl in zip(_console_handlers, old_levels):
            h.setLevel(lvl)

