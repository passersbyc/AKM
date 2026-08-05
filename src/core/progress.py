"""统一进度条显示 — rich 驱动。

两行式布局（TTY 动画 / 非终端自动禁用渲染），紧凑宽度适配 60+ 列终端：
    (=^▽^=) 下载进度  ━━━━━━━━━━━━  94/171  [0:00:16]  5.6个/s
                        成功 94  失败 0  跳过 0

- 第一行：描述 + 进度条 + 完成数/总数 + 耗时 + 速率（无百分比列，避免与 n/total 重复）
- 第二行：成功/失败/跳过计数，按终端宽度居中对齐
- 暂停/取消等状态通过第一行动态 description 表达
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


class _RowColumn(ProgressColumn):
    """按行（主进度行 / 计数行）条件渲染：只对指定 task 行渲染内层列，其余行为空。"""

    def __init__(self, column: ProgressColumn, target: str, task_ids: dict):
        super().__init__()
        self._column = column
        self._target = target
        self._task_ids = task_ids

    def render(self, task) -> Text:
        if task.id != self._task_ids.get(self._target):
            return Text("")
        return self._column.render(task)


class CountsColumn(ProgressColumn):
    """成功/失败/跳过 三色计数列，读取外部 counts dict，按终端宽度居中对齐。"""

    def __init__(self, counts: dict, console: Console):
        super().__init__()
        self.counts = counts
        self._console = console

    def render(self, task) -> Text:
        c = self.counts
        t = Text()
        t.append("成功 ", style="green")
        t.append(str(c.get("success", 0)), style="green")
        t.append("  失败 ", style="red")
        t.append(str(c.get("failed", 0)), style="red")
        t.append("  跳过 ", style="yellow")
        t.append(str(c.get("skipped", 0)), style="yellow")
        # 居中到终端宽度（非精确双宽字符处理，视觉居中即可）
        width = self._console.width
        pad = max(0, (width - len(str(t))) // 2)
        if pad:
            return Text(" " * pad) + t
        return t


class RateColumn(ProgressColumn):
    """完成速率列（基于任务行自身的 completed/elapsed），挂主进度行。

    速率上限 999：刚开始时 elapsed≈0 会算出天文数字，限宽防止把行撑爆。
    """

    def render(self, task) -> Text:
        if task.elapsed <= 0 or task.completed <= 0:
            return Text("")
        rate = min(task.completed / task.elapsed, 999.0)
        return Text(f"  {rate:.1f}个/s", style="cyan")


def make_progress(counts: dict, desc: str = "进度",
                  total: int = 1) -> tuple[Progress, int, int]:
    """创建两行式进度条，返回 (progress, 主行task_id, 计数行task_id)。

    调用方需同步推进两行（用 advance() 辅助函数）。
    非终端环境（管道/重定向/后台）自动禁用渲染，不产生噪声。
    """
    task_ids: dict = {}

    def row(column: ProgressColumn, target: str) -> ProgressColumn:
        return _RowColumn(column, target, task_ids)

    progress = Progress(
        row(TextColumn("[bold magenta]{task.description}[/bold magenta]",
                       justify="left"), "main"),
        row(BarColumn(bar_width=10, complete_style="magenta",
                      finished_style="green"), "main"),
        row(TextColumn("{task.completed}/{task.total}"), "main"),
        row(TimeElapsedColumn(), "main"),
        row(RateColumn(), "main"),
        row(CountsColumn(counts, _console), "counts"),
        console=_console,
        disable=not _console.is_terminal,
    )
    main_id = progress.add_task(description=f"(=^▽^=) {desc}", total=total)
    counts_id = progress.add_task(description="", total=total)
    task_ids["main"] = main_id
    task_ids["counts"] = counts_id
    return progress, main_id, counts_id


def advance(progress: Progress, main_id: int, counts_id: int, n: int = 1) -> None:
    """同步推进主进度行与计数行。"""
    progress.update(main_id, advance=n)
    progress.update(counts_id, advance=n)


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

