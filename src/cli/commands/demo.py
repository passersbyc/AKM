"""demo 命令 — 电影级交互式功能演示。"""
import argparse
import time
import random
from src.cli.core import BaseCommand


class DemoCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "demo"

    @property
    def description(self) -> str:
        return "电影级功能演示导览"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--fast", action="store_true", help="快速模式，跳过动画")

    def execute(self, args: argparse.Namespace) -> int:
        if self._json_mode:
            return self._respond(True, data={"message": "demo not available in json mode"})
        fast = getattr(args, 'fast', False)
        return self._run_demo(fast=fast)

    def _sparkle(self, count=6):
        chars = ["✦", "✧", "⋆", "✶", "·", "˚"]
        return "  ".join(random.choice(chars) for _ in range(count))

    def _bar(self, width, val, max_val, color="cyan"):
        from rich.text import Text
        n = max(1, int(width * val / max_val)) if max_val > 0 else 0
        return Text("█" * n, style=f"bold {color}") + Text("░" * (width - n), style="dim")

    # ═══════════════════════════════════════════════════════════════
    # 主流程
    # ═══════════════════════════════════════════════════════════════

    def _run_demo(self, fast: bool = False) -> int:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich import box
        from art import text2art
        from src.core.database import get_db

        console = Console()
        db = get_db()

        total = db.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        authors = db.execute("SELECT COUNT(DISTINCT author_id) FROM works").fetchone()[0]
        series_n = db.execute("SELECT COUNT(DISTINCT series_id) FROM works WHERE series_id != ''").fetchone()[0]
        favs = db.execute("SELECT COUNT(*) FROM works WHERE favorite = 1").fetchone()[0]
        total_size_kb = db.execute("SELECT COALESCE(SUM(file_size_kb), 0) FROM works").fetchone()[0]
        avg_rating = db.execute("SELECT AVG(rating) FROM works WHERE rating > 0").fetchone()[0] or 0
        rated_count = db.execute("SELECT COUNT(*) FROM works WHERE rating > 0").fetchone()[0]
        source_count = db.execute("SELECT source, COUNT(*) FROM works WHERE source != '' GROUP BY source ORDER BY COUNT(*) DESC").fetchall()

        type_rows = db.execute(
            "SELECT file_type, COUNT(*), COALESCE(SUM(file_size_kb),0) FROM works "
            "WHERE file_type != '' GROUP BY file_type ORDER BY COUNT(*) DESC"
        ).fetchall()

        author_rows = db.execute(
            "SELECT a.name, COUNT(w.id), AVG(w.rating) FROM works w "
            "JOIN authors a ON w.author_id=a.id GROUP BY a.name "
            "ORDER BY COUNT(w.id) DESC LIMIT 6"
        ).fetchall()

        # 收藏推荐：高评分 + 已收藏
        top_rated = db.execute(
            "SELECT title, author_id, rating FROM works WHERE rating > 0 "
            "ORDER BY rating DESC LIMIT 5"
        ).fetchall()
        top_rated_named = []
        for tit, aid, rat in top_rated:
            aname = db.execute("SELECT name FROM authors WHERE id=?", (aid,)).fetchone()
            top_rated_named.append((tit, aname[0] if aname else "?", rat))

        # 最近入库
        recent = db.execute(
            "SELECT title, author_id, imported_at FROM works ORDER BY imported_at DESC LIMIT 5"
        ).fetchall()
        recent_named = []
        for tit, aid, imp in recent:
            aname = db.execute("SELECT name FROM authors WHERE id=?", (aid,)).fetchone()
            recent_named.append((tit, aname[0] if aname else "?", imp or ""))

        # 标签
        tag_rows_data = db.execute("SELECT tags FROM works WHERE tags != ''").fetchall()
        from collections import Counter
        tag_counter = Counter()
        for (t,) in tag_rows_data:
            for tag in t.split(","):
                tag = tag.strip()
                if tag:
                    tag_counter[tag] += 1

        logo = text2art("AKM", font="alpha")

        # ═══ 快速模式 ═══
        if fast:
            self._static_slideshow(console, logo, total, authors, series_n, favs,
                                   type_rows, author_rows, tag_counter,
                                   total_size_kb, avg_rating, source_count,
                                   top_rated_named, recent_named)
            return 0

        # ═══════════════════════════════════════════════
        # ACT 1: 片头渐入 + 进度条
        # ═══════════════════════════════════════════════
        console.clear()
        for i in range(21):
            bar_done = int(60 * i / 20)
            bar_left = 60 - bar_done
            pct = int(100 * i / 20)
            s = "  ".join(random.choice(["✦", "✧", "·"]) for _ in range(5))

            console.clear()
            console.print()
            console.print(Align.center(Text("✦ ✦ ✦  系统初始化  ✦ ✦ ✦", style="bold bright_cyan")))
            console.print()
            console.print(Align.center(
                Text("█" * bar_done, style="bold cyan") + Text("░" * bar_left, style="dim")))
            console.print(Align.center(Text(f"  {pct}%", style="dim")))
            console.print()
            console.print(Align.center(Text(s, style="dim")))
            time.sleep(0.05)
        time.sleep(0.2)

        # ═══════════════════════════════════════════════
        # ACT 2: alpha 标题逐行浮现
        # ═══════════════════════════════════════════════
        logo_lines = logo.rstrip('\n').split('\n')
        for step in range(len(logo_lines) + 3):
            console.clear()
            for li, line in enumerate(logo_lines):
                s = "bold cyan" if li < step else "rgb(8,20,30)"
                console.print(Align.center(Text(line, style=s)))
            if step >= len(logo_lines):
                console.print()
                console.print(Align.center(Text("✨  作 品 管 理 系 统", style="bold bright_white")))
            if step >= len(logo_lines) + 1:
                console.print(Align.center(Text("《 功 能 演 示 》", style="bold yellow")))
            if step >= len(logo_lines) + 2:
                console.print()
                console.print(Align.center(Text("按  Enter  开始导览 ...", style="dim italic")))
            time.sleep(0.1)
        input()

        # ═══════════════════════════════════════════════
        # ACT 3: 数据幻灯片 (带闪入动画)
        # ═══════════════════════════════════════════════
        slide_count = 8

        for idx in range(slide_count):
            body = self._slide_body(idx, total, authors, series_n, favs,
                                    type_rows, author_rows, tag_counter,
                                    total_size_kb, avg_rating, rated_count,
                                    source_count, top_rated_named, recent_named)
            # 边框闪入
            for bright in range(1, 6):
                b = bright / 5
                console.clear()
                console.print(Align.center(
                    self._slide_frame(idx + 1, slide_count, body,
                                      border=f"rgb({int(0*b)},{int(180*b)},{int(220*b)})")))
                time.sleep(0.03)
            frame = self._slide_frame(idx + 1, slide_count, body)
            console.clear()
            console.print(Align.center(frame))
            time.sleep(0.4)
            input()

        # ═══════════════════════════════════════════════
        # ACT 4: 谢幕动画
        # ═══════════════════════════════════════════════
        console.clear()
        for i in range(15):
            sparkles = self._sparkle(8)
            stars = "★" * (i // 3 + 1) + "☆" * (5 - i // 3)
            console.clear()
            console.print()
            console.print(Align.center(Text(sparkles, style="yellow")))
            console.print()
            console.print(Align.center(
                Text("🎬" if i < 5 else "🎉  演 示 结 束  🎉", style="bold bright_white")
            ))
            console.print()
            console.print(Align.center(Text(stars, style="yellow")))
            console.print()
            console.print(Align.center(Text("开始管理你的作品库吧！", style="dim italic")))
            console.print()
            console.print(Align.center(Text(sparkles, style="yellow")))
            time.sleep(0.08)
        time.sleep(0.5)
        console.clear()
        return 0

    # ═══════════════════════════════════════════════════════════════
    # 幻灯片帧
    # ═══════════════════════════════════════════════════════════════

    def _slide_frame(self, page, total, body, border="bright_cyan"):
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich import box

        header = Text(f"  {self._sparkle(3)}  第 {page} 页  {self._sparkle(3)}  ", style="dim")
        footer = Text()
        footer.append("◈" * page, style=f"bold {border}")
        footer.append("◇" * (total - page), style="dim")
        footer.append(f"  {page}/{total}   按 Enter 继续", style="dim")

        return Panel(
            body,
            title=header,
            subtitle=footer,
            title_align="center",
            subtitle_align="center",
            box=box.HEAVY,
            border_style=border,
            padding=(1, 4),
        )

    def _slide_body(self, idx, total, authors, series_n, favs,
                    type_rows, author_rows, tag_counter,
                    total_size_kb, avg_rating, rated_count,
                    source_count, top_rated_named, recent_named):
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich.columns import Columns
        from rich import box

        max_cnt = max((r[1] for r in type_rows), default=1)

        if idx == 0:
            t = Table(box=None, show_header=False, padding=(0, 2))
            t.add_column(style="bold cyan", width=12)
            t.add_column(style="bold yellow", justify="center", width=8)
            t.add_column(style="dim", width=8)
            t.add_column(style="bold cyan", width=12)
            t.add_column(style="bold yellow", justify="center", width=8)
            t.add_row("📚 作品总数", str(total), "", "👤 作者数", str(authors))
            t.add_row("📂 系列数", str(series_n), "", "♥ 收藏数", str(favs))
            t.add_row("⭐ 平均评分", f"{avg_rating:.1f}", "", "📊 已评分", str(rated_count))
            t.add_row("💾 总大小", f"{total_size_kb/1024:.2f} MB", "", "", "")
            return Panel(t, title="📚 库状态概览", title_align="center",
                         box=box.ROUNDED, border_style="cyan", padding=(1, 2))

        elif idx == 1:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("分类", style="bold magenta", width=8)
            t.add_column("数量", style="bold yellow", justify="center", width=6)
            t.add_column("占比", style="dim", justify="center", width=6)
            t.add_column("分布", width=24)
            for tp, cnt, _ in type_rows:
                pct = f"{cnt / total * 100:.0f}%" if total else "0%"
                bar = self._bar(20, cnt, max_cnt, "magenta")
                t.add_row(tp, str(cnt), pct, bar)
            return Panel(t, title="🎨 分类分布", title_align="center",
                         box=box.ROUNDED, border_style="magenta", padding=(1, 2))

        elif idx == 2:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("作者", style="bold green", width=12)
            t.add_column("作品", style="bold yellow", justify="center", width=6)
            t.add_column("均分", style="bold bright_white", justify="center", width=6)
            t.add_column("热度", width=24)
            for name, cnt, avg in author_rows:
                bar = self._bar(20, cnt, max((r[1] for r in author_rows), default=1), "green")
                t.add_row(name, str(cnt), f"{avg:.1f}" if avg else "-", bar)
            return Panel(t, title="👤 Top 作者排行", title_align="center",
                         box=box.ROUNDED, border_style="green", padding=(1, 2))

        elif idx == 3:
            tags = tag_counter.most_common(12)
            max_tc = max((c for _, c in tags), default=1)
            body_parts = []
            current = Text()
            for tag, cnt in tags:
                size = 1 + int(cnt / max_tc * 2)
                colors = ["dim", "blue", "bold blue", "bold bright_blue"]
                c = colors[min(size, len(colors) - 1)]
                current.append(f"  {tag}  ", style=c)
                if len(current.plain) > 36:
                    body_parts.append(current)
                    current = Text()
            if current.plain:
                body_parts.append(current)

            tag_body = Text()
            for i, line in enumerate(body_parts):
                if i > 0:
                    tag_body.append("\n")
                tag_body.append(line)
            return Panel(tag_body, title="🏷️  热门标签云", title_align="center",
                         box=box.ROUNDED, border_style="blue", padding=(1, 2))

        elif idx == 4:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("排名", style="bold yellow", justify="center", width=4)
            t.add_column("作品", style="bold bright_white", width=18)
            t.add_column("作者", style="green", width=10)
            t.add_column("评分", style="bold yellow", justify="center", width=6)
            for i, (tit, an, rat) in enumerate(top_rated_named):
                medal = ["🥇", "🥈", "🥉", "4", "5"][i]
                t.add_row(medal, tit, an, f"★ {rat}")
            return Panel(t, title="⭐ 高评分推荐", title_align="center",
                         box=box.ROUNDED, border_style="yellow", padding=(1, 2))

        elif idx == 5:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("作品", style="bold bright_white", width=20)
            t.add_column("作者", style="green", width=10)
            t.add_column("入库时间", style="dim", width=16)
            for tit, an, imp in recent_named:
                t.add_row(tit, an, imp[:16] if imp else "-")
            return Panel(t, title="🕐 最近入库", title_align="center",
                         box=box.ROUNDED, border_style="bright_cyan", padding=(1, 2))

        elif idx == 6:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("来源", style="bold cyan", width=12)
            t.add_column("数量", style="bold yellow", justify="center", width=8)
            t.add_column("占比", style="dim", justify="center", width=8)
            for src, cnt in source_count:
                pct = f"{cnt / total * 100:.0f}%" if total else "0%"
                t.add_row(src, str(cnt), pct)
            return Panel(t, title="☁️  来源分布", title_align="center",
                         box=box.ROUNDED, border_style="cyan", padding=(1, 2))

        else:
            t = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            t.add_column("命令", style="bold bright_cyan", width=28)
            t.add_column("说明", style="dim", width=18)
            for cmd, desc in [
                ("akm list book", "查看所有作品"),
                ("akm list author", "查看作者列表"),
                ("akm search --keyword <词>", "关键词搜索"),
                ("akm stats", "库统计概览"),
                ("akm info <ID>", "作品详细信息"),
                ("akm import <文件>", "导入文件"),
                ("akm export <作者>", "导出作品"),
                ("akm demo", "重新观看演示"),
            ]:
                t.add_row(cmd, desc)
            return Panel(t, title="⚡ 常用命令速查", title_align="center",
                         box=box.ROUNDED, border_style="bright_cyan", padding=(1, 2))

    # ═══════════════════════════════════════════════════════════════
    # 快速模式
    # ═══════════════════════════════════════════════════════════════

    def _static_slideshow(self, console, logo, total, authors, series_n, favs,
                          type_rows, author_rows, tag_counter,
                          total_size_kb, avg_rating, source_count,
                          top_rated_named, recent_named):
        from rich.panel import Panel
        from rich.text import Text
        from rich.align import Align
        from rich.rule import Rule
        from rich import box

        slides = [
            Panel(Align.center(
                Text(logo.rstrip(), style="bold cyan")
                + Text("\n\n✨  作品管理系统  ·  功能演示", style="bold bright_white")
            ), box=box.HEAVY, border_style="bright_cyan", padding=(1, 4)),
        ]
        for i in range(8):
            slides.append(self._slide_body(
                i, total, authors, series_n, favs,
                type_rows, author_rows, tag_counter,
                total_size_kb, avg_rating, 0, source_count,
                top_rated_named, recent_named
            ))

        console.clear()
        total_slides = len(slides)
        for i, content in enumerate(slides):
            console.print()
            console.print(Rule(f"  {i + 1} / {total_slides}", style="dim"))
            console.print()
            console.print(Align.center(content))
            console.print()
            if i == 0:
                try:
                    input()
                except (EOFError, KeyboardInterrupt):
                    pass
            else:
                time.sleep(0.3)

        console.print()
        console.print(Align.center(Panel(
            Align.center(Text("🎉  演示结束！\n", style="bold bright_white")
                         + Text("输入 help 查看完整命令列表", style="dim")),
            box=box.DOUBLE, border_style="bright_cyan", padding=(1, 2))))
        console.print()
