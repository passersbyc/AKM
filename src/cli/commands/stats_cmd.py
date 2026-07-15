import argparse
from collections import Counter

from src.cli.base import BaseCommand
from src.core.database import short_id
from src.operations import get_stats


# 繁→简 标签归一化表（日文汉字繁体 → 中文简体）
TAG_NORMALIZE: dict[str, str] = {
    "性転換": "性转",
    "性転換過程": "性转换过程",
    "記憶改変": "记忆改変",
    "現実改変": "现实改変",
    "精神変化": "精神变化",
    "他者変身": "他者变身",
    "強制変身": "强制变身",
    "口調強制": "口调强制",
    "人格変化": "人格变化",
    "人格改変": "人格改変",
    "立場逆転": "立场逆转",
    "立場変化": "立场变化",
    "他人変身": "他人变身",
    "認識改変": "认识改変",
    "存在改変": "存在改変",
    "常識改変": "常识改変",
    "人生改変": "人生改変",
    "肉体変化": "肉体变化",
    "転生": "转生",
    "中国语": "中国語",
}


def _normalize_tag(tag: str) -> str:
    """归一化标签：繁→简、大小写统一。"""
    t = TAG_NORMALIZE.get(tag, tag)
    # TSF/tsf 统一为大写
    if t.lower() == "tsf":
        return "TSF"
    return t


class StatsCommand(BaseCommand):
    verb = "stats"
    nouns: list[str] = []
    description = "库仪表盘：统计 + 最近活动 + 猜你喜欢 + 标签/作者/点赞排行"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        stats = get_stats()

        if self.output.json_mode:
            return self.output.result(True, data=stats)

        from rich.console import Console
        from rich.table import Table
        from rich.rule import Rule
        from rich import box

        console = Console(stderr=True)

        # ── 库统计概览 ──
        console.print()
        console.print(Rule("[bold bright_cyan]库统计[/bold bright_cyan]", style="bright_cyan"))
        overview = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        overview.add_column(style="dim")
        overview.add_column(style="bold yellow")
        overview.add_column(style="dim")
        overview.add_column(style="bold yellow")
        overview.add_column(style="dim")
        overview.add_column(style="bold yellow")
        overview.add_column(style="dim")
        overview.add_column(style="bold yellow")
        overview.add_row(
            "作品", str(stats["total_books"]),
            "作者", str(stats["total_authors"]),
            "系列", str(stats["total_series"]),
            "收藏", str(stats["favorited_count"]),
        )
        console.print(overview)
        console.print(f"  [dim]总大小: {stats['total_size_mb']} MB[/dim]")
        console.print()

        # ── 最近活动 + 猜你喜欢（复用 banner 逻辑） ──
        from src.core.database import get_db
        db = get_db()

        recent_open = db.execute(
            "SELECT work_id, title, opened_at FROM recent_opens ORDER BY opened_at DESC LIMIT 5"
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
            console.print(Rule("[bold bright_cyan]最近活动[/bold bright_cyan]", style="bright_cyan"))
            activity = Table(show_header=True, header_style="bold bright_cyan",
                             box=box.SIMPLE_HEAVY, padding=(0, 1), expand=True)
            activity.add_column("最近打开", style="green", ratio=1)
            activity.add_column("最近导入", style="yellow", ratio=1)
            activity.add_column("最近下载", style="blue", ratio=1)

            def _fmt(row, id_key):
                if not row:
                    return "[dim]无[/dim]"
                sid = short_id(row[id_key])
                t = (row["title"] or "")[:12]
                return f"[cyan]{sid}[/cyan] {t}"

            for i in range(5):
                o = recent_open[i] if i < len(recent_open) else None
                im = recent_import[i] if i < len(recent_import) else None
                dl = recent_download[i] if i < len(recent_download) else None
                activity.add_row(_fmt(o, "work_id"), _fmt(im, "id"), _fmt(dl, "id"))
            console.print(activity)
            console.print()

            # 猜你喜欢
            from src.cli.ui.banner import _render_recommendations
            _render_recommendations(console, db, recent_open, recent_import, recent_download)

        # ── 标签统计 Top 10 ──
        all_tags = db.execute("SELECT tags FROM works WHERE tags != ''").fetchall()
        tag_counter: Counter = Counter()
        for r in all_tags:
            for t in (r["tags"] or "").split(","):
                t = t.strip()
                if t:
                    tag_counter[_normalize_tag(t)] += 1

        if tag_counter:
            console.print()
            console.print(Rule("[bold bright_cyan]标签统计 Top 10[/bold bright_cyan]", style="bright_cyan"))
            top_tags = tag_counter.most_common(10)
            max_count = top_tags[0][1] if top_tags else 1
            tag_table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
            tag_table.add_column("tag", style="cyan", no_wrap=True, width=16)
            tag_table.add_column("bar", ratio=1)
            tag_table.add_column("count", style="yellow", justify="right", width=6)
            for tag, count in top_tags:
                bar_len = max(1, int(count / max_count * 40))
                bar = "█" * bar_len
                tag_table.add_row(tag, f"[dim]{bar}[/dim]", str(count))
            console.print(tag_table)

        # ── 作者统计 Top 5 ──
        author_rows = db.execute(
            "SELECT a.name, COUNT(w.id) as cnt, SUM(CASE WHEN w.favorite = 1 THEN 1 ELSE 0 END) as fav_cnt "
            "FROM authors a JOIN works w ON a.id = w.author_id "
            "GROUP BY a.id ORDER BY cnt DESC LIMIT 5"
        ).fetchall()

        if author_rows:
            console.print()
            console.print(Rule("[bold bright_cyan]作者统计 Top 5[/bold bright_cyan]", style="bright_cyan"))
            author_table = Table(show_header=True, header_style="bold", box=box.SIMPLE, padding=(0, 1))
            author_table.add_column("作者", style="bold")
            author_table.add_column("作品数", justify="right", style="green")
            author_table.add_column("收藏数", justify="right", style="red")
            for r in author_rows:
                author_table.add_row(r["name"], str(r["cnt"]), str(r["fav_cnt"]))
            console.print(author_table)

        # ── 点赞排行 Top 5 ──
        like_rows = db.execute(
            "SELECT pl.work_id, pl.title, pl.author, pl.like_count "
            "FROM pixiv_likes pl ORDER BY pl.like_count DESC LIMIT 5"
        ).fetchall()

        if like_rows:
            console.print()
            console.print(Rule("[bold bright_cyan]点赞排行 Top 5[/bold bright_cyan]", style="bright_cyan"))
            like_table = Table(show_header=True, header_style="bold", box=box.SIMPLE, padding=(0, 1))
            like_table.add_column("ID", style="dim", width=12)
            like_table.add_column("标题", style="green", ratio=1)
            like_table.add_column("作者", style="blue")
            like_table.add_column("点赞", justify="right", style="yellow")
            for r in like_rows:
                like_table.add_row(r["work_id"], (r["title"] or "")[:20], r["author"] or "", str(r["like_count"]))
            console.print(like_table)

        console.print()
        return 0
