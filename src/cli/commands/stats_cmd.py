import argparse

from src.cli.base import BaseCommand
from src.core.database import short_id
from src.operations import get_stats, get_recent_activity, get_top_tags, get_top_authors, get_top_likes


def _human_size(kb: float) -> str:
    if kb >= 1024 ** 2:
        return f"{kb / 1024 ** 2:.2f} GB"
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb:.0f} KB"


def _fmt(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n or 0)


class StatsCommand(BaseCommand):
    verb = "stats"
    nouns: list[str] = []
    description = "库仪表盘：概览 + 分类/状态 + 最近活动 + 标签/作者/点赞排行"
    group = "浏览 (・ω・)"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--top", type=int, default=10,
                            help="排行数量（默认 10）")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        stats = get_stats()
        top = max(1, args.top)

        if self.output.json_mode:
            return self.output.result(True, data=stats)

        from rich.console import Console
        from rich.table import Table
        from rich.rule import Rule
        from rich import box

        console = Console(stderr=True)
        total = stats["total_books"] or 1

        # ── 概览 ──
        console.print()
        console.print(Rule("[bold bright_cyan]库统计 (◕‿◕)[/bold bright_cyan]", style="bright_cyan"))
        console.print(
            f"  [dim]作品[/dim] [bold yellow]{_fmt(stats['total_books'])}[/bold yellow]"
            f"   [dim]作者[/dim] [bold yellow]{_fmt(stats['total_authors'])}[/bold yellow]"
            f"   [dim]系列[/dim] [bold yellow]{_fmt(stats['total_series'])}[/bold yellow]"
            f"   [dim]收藏[/dim] [bold yellow]{_fmt(stats['favorited_count'])}[/bold yellow]"
        )
        console.print(
            f"  [dim]评分作品[/dim] [bold yellow]{_fmt(stats['rated_count'])}[/bold yellow]"
            f"   [dim]平均评分[/dim] [bold yellow]{stats['avg_rating'] or '-'}[/bold yellow]"
            f"   [dim]点赞合计[/dim] [bold yellow]{_fmt(stats['liked_count'])}[/bold yellow]"
            f"   [dim]总大小[/dim] [bold yellow]{_human_size(stats['total_size_kb'])}[/bold yellow]"
        )
        console.print()

        # ── 分类分布 ──
        type_dist = stats["type_distribution"]
        if type_dist:
            console.print(Rule("[bold bright_cyan]分类分布[/bold bright_cyan]", style="bright_cyan"))
            type_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            type_table.add_column("分类", style="bold cyan", width=6)
            type_table.add_column("bar", ratio=1)
            type_table.add_column("数量", style="yellow", justify="right", width=10)
            type_table.add_column("占比", style="dim", justify="right", width=8)
            max_cnt = max(type_dist.values())
            block = "\u2588"
            for ftype, cnt in type_dist.items():
                bar_len = max(1, int(cnt / max_cnt * 30))
                pct = f"{cnt / total * 100:.1f}%"
                type_table.add_row(ftype, f"[dim]{block * bar_len}[/dim]", _fmt(cnt), pct)
            console.print(type_table)
            console.print()

        # ── 库状态 ──
        follow_stats = stats.get("follow_stats") or {}
        parts = []
        for status in ("active", "paused", "dead"):
            if follow_stats.get(status):
                label = {"active": "活跃", "paused": "暂停", "dead": "停更"}[status]
                parts.append(f"{label} {follow_stats[status]}")
        follow_desc = f"[yellow]关注 {sum(follow_stats.values())}[/yellow]" + (f"（{' · '.join(parts)}）" if parts else "")
        src_desc = " · ".join(
            f"{name} {cnt}" for name, cnt in (stats.get("source_distribution") or {}).items()
        )
        status_line = (
            f"  {follow_desc}\n"
            f"  [dim]待下载 {stats['queue_pending']}[/dim] | "
            f"[dim]源失效标记 {stats['deleted_count']}[/dim] | "
            f"[dim]来源分布: {src_desc}[/dim]"
        )
        console.print(Rule("[bold bright_cyan]库状态[/bold bright_cyan]", style="bright_cyan"))
        console.print(status_line)
        console.print()

        # ── 最近活动 ──
        activity = get_recent_activity()
        recent_open = activity["recent_open"]
        recent_import = activity["recent_import"]
        recent_download = activity["recent_download"]

        if recent_open or recent_import or recent_download:
            console.print(Rule("[bold bright_cyan]最近活动[/bold bright_cyan]", style="bright_cyan"))
            act = Table(show_header=True, header_style="bold bright_cyan",
                        box=box.SIMPLE_HEAVY, padding=(0, 1), expand=True)
            act.add_column("最近打开", style="green", ratio=1)
            act.add_column("最近导入", style="yellow", ratio=1)
            act.add_column("最近下载", style="blue", ratio=1)

            def _fmt_activity(row, id_key):
                if not row:
                    return "[dim]无[/dim]"
                sid = short_id(row[id_key])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            for i in range(5):
                o = recent_open[i] if i < len(recent_open) else None
                im = recent_import[i] if i < len(recent_import) else None
                dl = recent_download[i] if i < len(recent_download) else None
                act.add_row(_fmt_activity(o, "work_id"), _fmt_activity(im, "id"), _fmt_activity(dl, "id"))
            console.print(act)
            console.print()

            # 猜你喜欢
            from src.cli.ui.banner import _render_recommendations
            _render_recommendations(console, recent_open, recent_import, recent_download)

        # ── 标签排行 ──
        top_tags = get_top_tags(limit=top)
        if top_tags:
            console.print()
            console.print(Rule(f"[bold bright_cyan]标签排行 Top {len(top_tags)}[/bold bright_cyan]", style="bright_cyan"))
            max_count = top_tags[0][1] if top_tags else 1
            tag_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            tag_table.add_column("tag", style="cyan", no_wrap=True, width=16)
            tag_table.add_column("bar", ratio=1)
            tag_table.add_column("count", style="yellow", justify="right", width=8)
            block = "\u2588"
            for tag, count in top_tags:
                bar_len = max(1, int(count / max_count * 40))
                tag_table.add_row(tag, f"[dim]{block * bar_len}[/dim]", _fmt(count))
            console.print(tag_table)

        # ── 作者排行 ──
        author_rows = get_top_authors(limit=top)
        if author_rows:
            console.print()
            console.print(Rule(f"[bold bright_cyan]作者排行 Top {len(author_rows)}[/bold bright_cyan]", style="bright_cyan"))
            author_table = Table(show_header=True, header_style="bold", box=box.SIMPLE, padding=(0, 1))
            author_table.add_column("作者", style="bold")
            author_table.add_column("作品数", justify="right", style="green")
            author_table.add_column("收藏数", justify="right", style="red")
            author_table.add_column("bar", ratio=1)
            max_cnt = author_rows[0]["cnt"] if author_rows else 1
            block = "\u2588"
            for r in author_rows:
                bar_len = max(1, int(r["cnt"] / max_cnt * 30))
                author_table.add_row(
                    (r["name"] or "")[:20], _fmt(r["cnt"]), _fmt(r["fav_cnt"]),
                    f"[dim]{block * bar_len}[/dim]",
                )
            console.print(author_table)

        # ── 点赞排行 ──
        like_rows = get_top_likes(limit=top)
        if like_rows:
            console.print()
            console.print(Rule(f"[bold bright_cyan]点赞排行 Top {len(like_rows)}[/bold bright_cyan]", style="bright_cyan"))
            like_table = Table(show_header=True, header_style="bold", box=box.SIMPLE, padding=(0, 1))
            like_table.add_column("ID", style="dim", width=12)
            like_table.add_column("标题", style="green", ratio=1)
            like_table.add_column("作者", style="blue")
            like_table.add_column("点赞", justify="right", style="yellow")
            for r in like_rows:
                like_table.add_row(
                    r["work_id"], (r["title"] or "")[:24], (r["author"] or "")[:14],
                    _fmt(r["like_count"]),
                )
            console.print(like_table)

        console.print()
        return 0
