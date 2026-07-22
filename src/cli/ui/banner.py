"""交互模式横幅与首次欢迎界面（从旧 core.py 拆出）。"""
from src.core.logging import logger


def _console():
    from rich.console import Console
    return Console(stderr=True)


def _render_recommendations(console, recent_open, recent_import, recent_download) -> None:
    """猜你喜欢 — 调 recommend_op 纯数据 + rich 渲染。"""
    try:
        from rich.table import Table
        from rich import box
    except ImportError:
        return

    from src.operations.recommend_op import get_recommendations
    picked = get_recommendations(limit=8)
    if not picked:
        return

    console.print()
    rec_table = Table(title="[bold bright_magenta]猜你喜欢[/bold bright_magenta]",
                      show_header=False, box=box.SIMPLE_HEAVY, padding=(0, 1),
                      expand=True)
    rec_table.add_column("id", width=11, no_wrap=True)
    rec_table.add_column("title", ratio=1, no_wrap=True, overflow="ellipsis")
    rec_table.add_column("count", width=6, no_wrap=True)
    rec_table.add_column("reason", width=24, no_wrap=True)
    for item in picked:
        reason_str = ""
        if item["reasons"]:
            reason_str = "[" + ", ".join(item["reasons"][:2]) + "]"
        if item["kind"] == "work":
            title = (item["title"] or "")[:20]
            rec_table.add_row(
                f"[cyan]{item['short_id']}[/cyan]",
                title,
                "",
                f"[dim]{reason_str}[/dim]" if reason_str else "",
            )
        else:
            name_trunc = (item["title"] or "")[:20]
            rec_table.add_row(
                f"[magenta]\u25a3[/magenta] [cyan]{item['short_id']}[/cyan]",
                f"[bold magenta]{name_trunc}[/bold magenta]",
                f"[dim]{item['series_count']}本[/dim]",
                f"[dim]{reason_str}[/dim]" if reason_str else "",
            )
    console.print(rec_table)


def show_interactive_banner(prog_name: str) -> None:
    try:
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich.rule import Rule
        from rich import box
        from art import text2art
        from src.core.database import get_db

        console = _console()
        db = get_db()
        total_works = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        total_authors = db.execute("SELECT COUNT(DISTINCT author_id) FROM works").fetchone()[0]
        total_series = db.execute("SELECT COUNT(DISTINCT series_id) FROM works WHERE series_id != ''").fetchone()[0]
        total_fav = db.execute("SELECT COUNT(*) FROM works WHERE favorite = 1").fetchone()[0]

        console.print()
        console.print(Rule(style="bright_cyan"))

        logo = text2art("AKM", font="merlin1")
        logo_text = Text()
        for line in logo.rstrip("\n").split("\n"):
            logo_text.append(line + "\n", style="bold cyan")
        console.print()
        console.print(Align.center(logo_text))

        subtitle = Panel(
            Align.center(Text("作品管理系统  ·  v0.2.0", style="bold bright_white")),
            box=box.HEAVY,
            border_style="bright_cyan",
            padding=(0, 6),
        )
        console.print(Align.center(subtitle))

        console.print()
        stats_line = Text()
        stats_line.append("  作品 ", style="dim")
        stats_line.append(str(total_works), style="bold yellow")
        stats_line.append("    作者 ", style="dim")
        stats_line.append(str(total_authors), style="bold yellow")
        stats_line.append("    系列 ", style="dim")
        stats_line.append(str(total_series), style="bold yellow")
        stats_line.append("    收藏 ", style="dim")
        stats_line.append(str(total_fav), style="bold yellow")
        console.print(Align.center(stats_line))

        # ── 最近活动三栏 ──
        recent_open = db.execute(
            "SELECT work_id, title, opened_at FROM recent_opens "
            "ORDER BY opened_at DESC LIMIT 5"
        ).fetchall()
        recent_import = db.execute(
            "SELECT id, title, imported_at FROM works "
            "WHERE imported_at != '' AND (source = '' OR source = 'local' OR source = 'demo' OR source NOT LIKE 'http%') "
            "ORDER BY imported_at DESC LIMIT 5"
        ).fetchall()
        recent_download = db.execute(
            "SELECT id, title, imported_at, source FROM works "
            "WHERE imported_at != '' AND source LIKE 'http%' "
            "ORDER BY imported_at DESC LIMIT 5"
        ).fetchall()

        if recent_open or recent_import or recent_download:
            console.print()
            activity = Table(show_header=True, header_style="bold bright_cyan",
                             box=box.SIMPLE_HEAVY, padding=(0, 1), expand=True)
            activity.add_column("最近打开", style="green", ratio=1)
            activity.add_column("最近导入", style="yellow", ratio=1)
            activity.add_column("最近下载", style="blue", ratio=1)

            def _fmt_open(row):
                if not row:
                    return "[dim]无[/dim]"
                from src.core.database import short_id
                sid = short_id(row["work_id"])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            def _fmt_import(row):
                if not row:
                    return "[dim]无[/dim]"
                from src.core.database import short_id
                sid = short_id(row["id"])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            def _fmt_download(row):
                if not row:
                    return "[dim]无[/dim]"
                from src.core.database import short_id
                sid = short_id(row["id"])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            for i in range(5):
                o = recent_open[i] if i < len(recent_open) else None
                im = recent_import[i] if i < len(recent_import) else None
                dl = recent_download[i] if i < len(recent_download) else None
                activity.add_row(_fmt_open(o), _fmt_import(im), _fmt_download(dl))
            console.print(activity)

            # ── 猜你喜欢（推荐） ──
            _render_recommendations(console, recent_open, recent_import, recent_download)

        console.print()
        shortcuts = Table(show_header=False, box=box.SIMPLE, padding=(0, 3))
        shortcuts.add_column(width=24)
        shortcuts.add_column(width=24)
        shortcuts.add_column(width=24)
        shortcuts.add_row(
            "[bold cyan]list[/]  [dim]查看作品[/]",
            "[bold cyan]search[/]  [dim]搜索[/]",
            "[bold cyan]stats[/]  [dim]仪表盘[/]",
        )
        shortcuts.add_row(
            "[bold cyan]import[/]  [dim]导入[/]",
            "[bold cyan]open[/]  [dim]打开[/]",
            "[bold cyan]follow[/]  [dim]关注/同步[/]",
        )
        console.print(Align.center(shortcuts))

        console.print()
        tip = Panel(
            Align.center(
                Text("输入 ", style="dim")
                + Text("help", style="bold bright_white")
                + Text(" 查看命令  |  ", style="dim")
                + Text("输入 ", style="dim")
                + Text("exit", style="bold bright_white")
                + Text(" 退出", style="dim")
            ),
            box=box.SIMPLE,
            border_style="bright_black",
            padding=(0, 4),
        )
        console.print(Align.center(tip))
        console.print(Rule(style="bright_cyan"))
        console.print()
    except Exception:
        print(f"\n欢迎使用 {prog_name} 交互模式。\n输入 'help' 或 '?' 查看命令。输入 'exit' 退出。\n")


def show_welcome(prog_name: str) -> None:
    try:
        from src.core.database import get_db
        db = get_db()
        total = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        if total > 0:
            return
    except Exception:
        pass

    try:
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich.columns import Columns
        from rich.align import Align
        from rich.rule import Rule
        from rich import box
        from art import text2art

        console = _console()
        logo = text2art("AKM", font="alpha")
        lines = [l for l in logo.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        logo_text = Text()
        for i, line in enumerate(lines):
            logo_text.append(line + ("\n" if i < len(lines) - 1 else ""), style="bold cyan")
        console.print(Align.center(logo_text))

        subtitle = Panel(
            Align.center(Text("作 品 管 理 系 统  ·  v0.2.0", style="bold")),
            box=box.HEAVY,
            border_style="bright_cyan",
            padding=(0, 4),
        )
        console.print(Align.center(subtitle))
        console.print()

        features = [
            Panel(
                Text("作品管理\n", style="bold yellow")
                + Text("导入 / 搜索 / 编辑\n分类 / 标签 / 评分", style="dim"),
                box=box.ROUNDED, border_style="yellow", padding=(1, 2),
            ),
            Panel(
                Text("多格式支持\n", style="bold magenta")
                + Text("txt · epub · pdf\n漫画 · 音乐 · 电影", style="dim"),
                box=box.ROUNDED, border_style="magenta", padding=(1, 2),
            ),
            Panel(
                Text("在线订阅\n", style="bold blue")
                + Text("follow / pull\nPixiv 作者追踪", style="dim"),
                box=box.ROUNDED, border_style="blue", padding=(1, 2),
            ),
            Panel(
                Text("智能检索\n", style="bold green")
                + Text("正则搜索 · 多字段\n收藏 · 作者 · 系列", style="dim"),
                box=box.ROUNDED, border_style="green", padding=(1, 2),
            ),
        ]
        console.print(Columns(features, equal=True, padding=(0, 1)))

        console.print()
        console.print(Rule("快速上手", style="bold bright_cyan"))
        cmd_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2),
                          expand=True, leading=1)
        cmd_table.add_column("cmd", style="bold cyan", width=35)
        cmd_table.add_column("desc", style="white")
        for cmd, desc in [
            ("akm ls", "查看库中所有作品"),
            ("akm search <关键词>", "搜索作品"),
            ("akm open <作品ID>", "在应用中打开作品"),
            ("akm stats", "库统计概览"),
            ("akm import <文件路径>", "导入新文件到库中"),
            ("akm follow <Pixiv URL>", "关注 Pixiv 作者"),
        ]:
            cmd_table.add_row(f"  $ {cmd}", desc)
        console.print(Panel(cmd_table, box=box.ROUNDED, border_style="bright_black"))
        console.print()

        footer = Text()
        footer.append("输入 ", style="dim")
        footer.append("akm --help", style="bold bright_white")
        footer.append(" 查看完整命令  |  输入 ", style="dim")
        footer.append("akm", style="bold bright_white")
        footer.append(" 进入交互模式", style="dim")
        console.print(Align.center(footer))
        console.print()
    except Exception:
        print(f"\n欢迎使用 {prog_name}！输入 --help 查看帮助。\n")
