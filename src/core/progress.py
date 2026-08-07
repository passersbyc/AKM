"""统一进度条显示 — rich 驱动。

两行式布局（TTY 动画 / 非终端自动禁用渲染）：
    (◕‿◕) 同步检查  ━━━━━━━━━━  165/175  [0:00:11]  14.9个/s
                      成功165  失败0  跳过0

- 第一行：描述 + 进度条 + 完成数/总数 + 耗时 + 速率
- 第二行：成功/失败/跳过计数，独立表格渲染（列不与主行共享），
  居中显示且位置稳定，不会因终端宽度/动画刷新而抖动错位
- 两行各自 no_wrap：窄终端截断而非换行，布局永不被破坏
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
from rich.table import Table
from rich.text import Text

# 进度条统一输出到 stderr（与日志同侧，不污染 stdout 的 --json 输出）
_console = Console(stderr=True)


class CountsColumn(ProgressColumn):
    """成功/失败/跳过 三色计数列，读取外部 counts dict。"""

    def __init__(self, counts: dict, console: Console):
        super().__init__()
        self.counts = counts
        self._console = console

    def render(self, task) -> Text:
        c = self.counts
        t = Text()
        t.append(f"成功{c.get('success', 0)}", style="green")
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


class _TwoRowProgress(Progress):
    """两行式进度：主进度行 + 计数行，各自独立表格渲染。

    通过覆盖 get_renderables 让两行使用不同的列集，计数行不再继承
    主行的占位列宽，且可独立居中，窄终端下各自截断而非换行错位。
    """

    def __init__(self, main_columns, counts_columns, **kwargs):
        self._main_columns = list(main_columns)
        self._counts_columns = list(counts_columns)
        self._main_ids: set[int] = set()
        self._counts_ids: set[int] = set()
        super().__init__(
            *self._main_columns, *self._counts_columns, **kwargs
        )

    def _render_group(self, columns, tasks, *, expand=False, center=False) -> Table:
        table_columns = []
        for c in columns:
            col = c.get_table_column().copy()
            col.no_wrap = True
            if center:
                col.justify = "center"
            table_columns.append(col)
        table = Table.grid(*table_columns, padding=(0, 1), expand=expand)
        for task in tasks:
            if task.visible:
                table.add_row(*(c(task) for c in columns))
        return table

    def get_renderables(self):
        main_tasks = [t for t in self.tasks if t.id in self._main_ids]
        counts_tasks = [t for t in self.tasks if t.id in self._counts_ids]
        out = []
        if main_tasks:
            out.append(self._render_group(self._main_columns, main_tasks))
        if counts_tasks:
            out.append(self._render_group(self._counts_columns, counts_tasks,
                                          expand=True, center=True))
        return out


def make_progress(counts: dict, desc: str = "进度",
                  total: int = 1) -> tuple[Progress, int, int]:
    """创建两行式进度条，返回 (progress, 主行task_id, 计数行task_id)。

    调用方用 advance() 同步推进两行。
    非终端环境（管道/重定向/后台）自动禁用渲染，不产生噪声。
    """
    progress = _TwoRowProgress(
        [
            TextColumn("[bold magenta]{task.description}[/bold magenta]",
                       justify="left"),
            BarColumn(bar_width=8, complete_style="magenta",
                      finished_style="green"),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            RateColumn(),
        ],
        [CountsColumn(counts, _console)],
        console=_console,
        disable=not _console.is_terminal,
    )
    main_id = progress.add_task(description=f"(◕‿◕) {desc}", total=total)
    counts_id = progress.add_task(description="", total=total)
    progress._main_ids = {main_id}
    progress._counts_ids = {counts_id}
    return progress, main_id, counts_id


def advance(progress: Progress, main_id: int, counts_id: int, n: int = 1) -> None:
    """同步推进主进度行与计数行（counts_id 为 None 时兼容单行场景）。"""
    progress.update(main_id, advance=n)
    if counts_id is not None:
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
