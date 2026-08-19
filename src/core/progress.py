"""统一进度条显示 — rich 驱动。

两行式布局（TTY 动画 / 非终端自动禁用渲染）：
    同步检查  ━━━━━━━━━━  165/175  94%  [0:00:11 0:00:01]  14.9个/s
               成功165  失败0  跳过0

- 第一行：描述 + 进度条 + 完成数/总数 + 百分比 + 耗时/剩余 + 速率
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
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

# 进度条统一输出到 stderr（与日志同侧，不污染 stdout 的 --json 输出）
_console = Console(stderr=True)


class CountsColumn(ProgressColumn):
    """成功/失败/跳过 三色计数列。

    优先从 task.fields["counts"] 读取计数（支持一个 Progress 实例承载
    多个站点的独立计数行）；未提供 fields 时回退到构造时传入的 counts。
    """

    def __init__(self, counts: dict | None = None, console: Console | None = None):
        super().__init__()
        self._default_counts = counts or {}
        self._console = console

    def render(self, task) -> Text:
        c = (task.fields or {}).get("counts") or self._default_counts
        t = Text("    ")  # 计数行缩进，与左端留出间距
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

    支持多组（站点）task 共享同一实例：_pairs 记录 (主行id, 计数行id)
    的配对顺序，get_renderables 按配对交错渲染，每个站点「主行+计数行」
    垂直堆叠，互不冲突。
    """

    def __init__(self, main_columns, counts_columns, **kwargs):
        self._main_columns = list(main_columns)
        self._counts_columns = list(counts_columns)
        # 有序配对：(主行 task_id, 计数行 task_id 或 None)
        self._pairs: list[tuple[int, int | None]] = []
        super().__init__(
            *self._main_columns, *self._counts_columns, **kwargs
        )

    def _add_pair(self, desc: str, total: int,
                  counts: dict | None) -> tuple[int, int | None]:
        """添加一组两行式 task，记录配对并返回 (main_id, counts_id)。"""
        main_id = self.add_task(description=desc, total=total)
        counts_id = None
        if counts is not None:
            counts_id = self.add_task(
                description="", total=total, counts=counts)
        self._pairs.append((main_id, counts_id))
        return main_id, counts_id

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
        out = []
        for main_id, counts_id in self._pairs:
            main_tasks = [t for t in self.tasks if t.id == main_id]
            counts_tasks = [t for t in self.tasks if t.id == counts_id]
            if main_tasks:
                out.append(self._render_group(self._main_columns, main_tasks))
            if counts_tasks:
                out.append(self._render_group(self._counts_columns, counts_tasks))
        return out


def make_progress(counts: dict | None, desc: str = "进度",
                  total: int = 1) -> tuple[Progress, int, int | None]:
    """创建两行式进度条，返回 (progress, 主行task_id, 计数行task_id)。

    调用方用 advance() 同步推进两行；counts 为 None 时只创建主行
    （计数行 task_id 返回 None），适合顺序处理场景。
    非终端环境（管道/重定向/后台）自动禁用渲染，不产生噪声。
    """
    progress = _TwoRowProgress(
        [
            TextColumn("[bold magenta]{task.description}[/bold magenta]",
                       justify="left"),
            BarColumn(bar_width=12, complete_style="magenta",
                      finished_style="green"),
            TextColumn("{task.completed}/{task.total}"),
            TextColumn("{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            RateColumn(),
        ],
        [CountsColumn(None, _console)] if counts is not None else [],
        console=_console,
        disable=not _console.is_terminal,
    )
    main_id, counts_id = progress._add_pair(desc, total, counts)
    return progress, main_id, counts_id


def add_progress_task(progress: Progress, counts: dict | None,
                      desc: str, total: int) -> tuple[int, int | None]:
    """在共享的两行式 Progress 实例上再添加一组 task（多站点并行下载）。

    返回 (main_id, counts_id)。调用方用 advance() 推进；由外部统一
    start()/stop() 该共享实例，不要在各自线程内重复 start/stop。
    """
    if isinstance(progress, _TwoRowProgress) and hasattr(progress, "_add_pair"):
        return progress._add_pair(desc, total, counts)
    main_id = progress.add_task(description=desc, total=total)
    counts_id = None
    if counts is not None:
        counts_id = progress.add_task(
            description="", total=total, counts=counts)
    return main_id, counts_id


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
