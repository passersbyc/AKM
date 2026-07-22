import argparse

from src.cli.base import BaseCommand
from src.core.database import short_id
from src.core.logging import logger
from src.operations import list_items


class ListCommand(BaseCommand):
    verb = "list"
    nouns = ["author", "download"]
    description = "列出库中的作品或作者"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("number", type=int, nargs="?", default=0,
                            help="限制显示数量（默认 300）")
        parser.add_argument("--sort-by", type=str, default="id",
                            choices=["author", "id", "title", "series", "like", "rating", "favorite"],
                            help="排序方式")
        parser.add_argument("--author", type=str, default="", help="按作者筛选")
        parser.add_argument("--type", type=str, default="", help="按分类筛选")
        parser.add_argument("--favorite", action="store_true", help="仅收藏项")
        parser.add_argument("--no-limit", action="store_true", help="输出全部")

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        if noun == "author":
            parser.add_argument("number", type=int, nargs="?", default=0,
                                help="限制显示数量")
            parser.add_argument("--favorite", action="store_true", help="仅收藏作者")
        elif noun == "download":
            parser.add_argument("--all", action="store_true", help="显示全部（含已下载/无效/拉黑）")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun == "author":
            return self._list_author(args)
        if noun == "download":
            return self._list_download(args)
        return self._list_work(args)

    def _list_work(self, args: argparse.Namespace) -> int:
        result = list_items("book", sort_by=args.sort_by, number=0)
        items = result["items"]

        if args.author:
            items = [r for r in items if args.author in r.get("作者", "")]
        if args.type:
            items = [r for r in items if args.type in (r.get("分类", "") or "")]
        if args.favorite:
            items = [r for r in items if r.get("收藏", "否") == "是"]
        total = len(items)

        if self.output.json_mode:
            return self.output.result(True, data={"works": items, "total": total})

        if not items:
            logger.info("库里空空如也")
            return 0

        limit = args.number if args.number > 0 else (0 if args.no_limit else 300)
        is_default_limit = not args.number and not args.no_limit
        if limit > 0 and len(items) > limit:
            items = items[:limit]

        from rich.table import Table

        table = Table(title="作品列表", show_lines=False)
        table.add_column("ID", justify="right", style="cyan", no_wrap=True)
        table.add_column("标题", style="magenta")
        table.add_column("作者", style="green")
        table.add_column("系列", style="yellow")
        table.add_column("分类", style="blue")
        table.add_column("收藏", style="red")
        table.add_column("点赞", style="yellow")
        table.add_column("评分", style="cyan")

        for i, row in enumerate(items):
            author = row.get("作者", "未知")
            is_last_of_author = (i + 1 == len(items)
                                 or items[i + 1].get("作者", "未知") != author)

            likes = row.get("点赞", "0") or "0"
            rating = row.get("评分", "-") or "0"
            table.add_row(
                short_id(row.get("ID", "N/A")),
                row.get("标题", ""),
                author,
                row.get("系列", "-") or "-",
                row.get("分类", "") or "未知",
                "♥" if row.get("收藏", "否") == "是" else "",
                likes if int(likes) > 0 else "",
                rating if float(rating) > 0 else "",
                end_section=is_last_of_author,
            )

        self.console.print(table)
        return 0

    def _list_author(self, args: argparse.Namespace) -> int:
        from src.operations import list_authors_with_status
        items = list_authors_with_status()
        if args.favorite:
            items = [a for a in items if a.get("favorite", False)]
        if args.number > 0:
            items = items[:args.number]

        if self.output.json_mode:
            return self.output.result(True, data={"authors": items, "total": len(items)})

        if not items:
            logger.info("还没有作者")
            return 0

        from rich.table import Table

        table = Table(title="作者列表", show_lines=False)
        table.add_column("ID", style="magenta", justify="right", width=4)
        table.add_column("名称", style="bold")
        table.add_column("收藏", style="red", width=4)
        table.add_column("状态", style="cyan", width=12)
        table.add_column("作品数", justify="right", style="green")
        table.add_column("系列数", justify="right", style="yellow")
        table.add_column("主页", style="dim", max_width=30)

        sorted_items = sorted(items, key=lambda r: (not r.get("favorite", False), r.get("id", "")))
        last_fav_idx = -1
        for i, row in enumerate(sorted_items):
            if row.get("favorite", False):
                last_fav_idx = i

        for i, row in enumerate(sorted_items):
            is_last_fav = (i == last_fav_idx and last_fav_idx >= 0)
            name = row.get("name", "")
            lid = row.get("id", "")
            homepage = row.get("homepage", "") or "-"
            if homepage != "-" and "//" in homepage:
                homepage = homepage.split("//", 1)[1]

            status = row.get("status", "")
            count = str(row.get("work_count", 0))
            scount = str(row.get("series_count", 0))
            fav = "[red]\u2665[/red]" if row.get("favorite") else ""

            table.add_row(lid, name, fav, status, count, scount, homepage,
                          end_section=is_last_fav)

        self.console.print(table)
        self.output.info(f"[dim]共计 {len(items)} 位作者[/dim]")
        return 0

    def _list_download(self, args: argparse.Namespace) -> int:
        from src.operations import list_download_queue
        from rich.table import Table

        rows = list_download_queue(show_all=getattr(args, "all", False))

        if not rows:
            self.output.info("下载队列为空")
            return 0

        if self.output.json_mode:
            items = [dict(r) for r in rows]
            return self.output.result(True, data={"queue": items, "total": len(items)})

        table = Table(title="下载队列", show_lines=False)
        table.add_column("URL", style="dim", max_width=50)
        table.add_column("作者", style="green")
        table.add_column("类型", style="blue", width=6)
        table.add_column("状态", style="cyan", width=10)
        table.add_column("失败", justify="right", style="yellow", width=4)
        table.add_column("添加时间", style="dim", width=16)

        for r in rows:
            url = r["url"] or ""
            author = r["author_name"] or "-"
            w_type = r["work_type"] or "-"
            fail_count = r["fail_count"]

            if not r["is_valid"]:
                status = "[red]无效[/red]"
            elif r["is_blacklisted"]:
                status = "[red]拉黑[/red]"
            elif r["is_in_db"]:
                status = "[green]已下载[/green]"
            else:
                status = "[yellow]待下载[/yellow]"

            # Truncate URL for display
            short_url = url
            if len(url) > 47:
                short_url = url[:44] + "..."

            table.add_row(
                short_url, author, w_type, status,
                str(fail_count) if fail_count else "",
                r["download_time"] or r["added_at"] or "",
            )

        self.console.print(table)
        total = len(rows)
        pending = sum(1 for r in rows if not r["is_in_db"] and r["is_valid"] and not r["is_blacklisted"])
        self.output.info(f"[dim]共 {total} 条 | 待下载: {pending}[/dim]")
        return 0
