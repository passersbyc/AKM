import argparse
from src.cli.core import BaseCommand
from src.operations import list_items
from src.core.logging import logger
from src.core.database import short_id

try:
    from rich.table import Table
except ImportError:
    Table = None


class ListCommand(BaseCommand):
    @property
    def description(self) -> str:
        return "列出库中的统计和详细信息（作品、作者、系列、分类）"

    @property
    def name(self) -> str:
        return "list"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target_type", nargs="?", default="",
                            help="资源类型 (book|author|series|type)")
        parser.add_argument("-w", "--work", action="store_true", help="[兼容] 同 list book")
        parser.add_argument("-a", "--author", action="store_true", help="[兼容] 同 list author")
        parser.add_argument("-s", "--series", action="store_true", help="[兼容] 同 list series")
        parser.add_argument("-t", "--type", action="store_true", help="[兼容] 同 list type")
        parser.add_argument("-n", "--number", type=int, default=0, help="限制显示数量")
        parser.add_argument("--no-limit", action="store_true", help="取消默认 300 行限制，输出全部")
        parser.add_argument("-p", "--page", type=int, default=0, metavar="SIZE",
                            help="分页输出，每页 SIZE 行（回车翻页）")
        parser.add_argument("--sort-by", type=str, default="id",
                            choices=["author", "id", "title", "series", "like", "rating", "favorite"],
                            help="排序方式（仅 book）")
        parser.add_argument("--last-f", action="store_true",
                            help="显示收藏作者最近一周的导入/更新")

    def execute(self, args: argparse.Namespace) -> int:
        tt = args.target_type
        if tt in ("book", "b"):
            show_work, show_author, show_series, show_type = True, False, False, False
        elif tt in ("author", "a"):
            show_work, show_author, show_series, show_type = False, True, False, False
        elif tt in ("series", "s"):
            show_work, show_author, show_series, show_type = False, False, True, False
        elif tt in ("type", "t"):
            show_work, show_author, show_series, show_type = False, False, False, True
        else:
            show_work = args.work
            show_author = args.author
            show_series = args.series
            show_type = args.type

        if not any([show_work, show_author, show_series, show_type]):
            text = "请指定资源类型: list {book|author|series|type} 或使用 -w/-a/-s/-t"
            if self._json_mode:
                return self._respond(False, error=text)
            logger.info(text)
            return 1

        if self._json_mode:
            data = {}
            if show_work:
                if args.last_f:
                    from src.operations.list_op import list_recent_favorited
                    items = list_recent_favorited(days=7)
                    data["works"] = items
                    data["recent_favorited"] = True
                    data["total"] = len(items)
                else:
                    result = list_items("book", sort_by=args.sort_by, number=args.number)
                    data["works"] = result["items"]
            if show_author:
                data["authors"] = list_items("author")["items"]
            if show_series:
                data["series"] = list_items("series")["items"]
            if show_type:
                result = list_items("type")
                data["types"] = result["items"]
            return self._respond(True, data=data)

        if show_work:
            if args.last_f:
                from src.operations.list_op import list_recent_favorited
                items = list_recent_favorited(days=7)
                total = len(items)
                if not items:
                    logger.info("收藏作者最近一周没有更新")
                else:
                    table = Table(title="收藏作者 · 最近一周更新", show_lines=False)
                    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
                    table.add_column("标题", style="magenta")
                    table.add_column("作者", style="green")
                    table.add_column("更新时间", style="yellow")
                    table.add_column("分类", style="blue")
                    table.add_column("点赞", style="yellow")
                    table.add_column("收藏", style="red")
                    for row in items:
                        table.add_row(
                            short_id(row.get("ID", "")),
                            row.get("标题", ""),
                            row.get("作者", ""),
                            row.get("导入时间", "-")[:10],
                            row.get("分类", "") or "未知",
                            row.get("点赞", "0") if int(row.get("点赞", "0") or "0") > 0 else "",
                            "\u2665" if row.get("收藏", "否") == "是" else "",
                        )
                    self.console.print(table)
                    self._print(f"[dim]共计 {total} 个作品[/dim]")
            else:
                result = list_items("book", sort_by=args.sort_by, number=0)
                total = result["total"]
                items = result["items"]
                if not items:
                    logger.info("库里空空如也")
                else:
                    limit = args.number if args.number > 0 else (0 if args.no_limit else 300)
                    is_default_limit = not args.number and not args.no_limit
                    if limit > 0 and len(items) > limit:
                        items = items[:limit]
                    page_size = args.page if args.page > 0 else len(items)

                    for page_start in range(0, len(items), page_size):
                        page_items = items[page_start:page_start + page_size]
                        table = Table(title="作品列表", show_lines=False)
                        table.add_column("ID", justify="right", style="cyan", no_wrap=True)
                        table.add_column("标题", style="magenta")
                        table.add_column("作者", style="green")
                        table.add_column("系列", style="yellow")
                        table.add_column("分类", style="blue")
                        table.add_column("收藏", style="red")
                        table.add_column("点赞", style="yellow")
                        table.add_column("评分", style="cyan")
                        last = len(page_items) - 1
                        for i, row in enumerate(page_items):
                            es = (i < last and row.get("作者", "") != page_items[i+1].get("作者", ""))
                            table.add_row(
                                short_id(row.get("ID", "N/A")), row.get("标题", ""),
                                row.get("作者", "未知"), row.get("系列", "-") or "-",
                                row.get("分类", "") or "未知",
                                row.get("收藏", "否") == "是" and "\u2665" or "",
                                row.get("点赞", "0") if int(row.get("点赞", "0") or "0") > 0 else "",
                                row.get("评分", "-") if float(row.get("评分", "0") or "0") > 0 else "",
                                end_section=es,
                            )
                        self.console.print(table)

                        p_end = page_start + len(page_items)
                        if args.page > 0:
                            self._print(f"[dim]{page_start + 1}-{p_end} / {total}[/dim]")
                        elif is_default_limit and limit < total:
                            self._print(f"[dim]显示 {p_end}/{total} 个作品（--no-limit 查看全部）[/dim]")
                        else:
                            self._print(f"[dim]共计 {total} 个作品[/dim]")

                        if args.page > 0 and page_start + args.page < len(items):
                            try:
                                input("按 Enter 继续...")
                            except (EOFError, KeyboardInterrupt):
                                self._print()
                                break

        if show_author:
            items = list_items("author")["items"]
            if items:
                from src.core.activity import compute_status, build_author_stats

                author_stats = build_author_stats()

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
                    src = row.get("source", "local")
                    tracking_status = row.get("follow_status", "")
                    homepage = row.get("homepage", "") or "-"
                    if homepage != "-" and "//" in homepage:
                        homepage = homepage.split("//", 1)[1]

                    st = author_stats.get(lid) or author_stats.get(name) or {}
                    status = compute_status(lid, src, tracking_status,
                                            row.get("last_checked", ""),
                                            stats=st if st else None)
                    count = str(row.get("work_count", 0))
                    scount = str(row.get("series_count", 0))
                    fav = "[red]\u2665[/red]" if row.get("favorite") else ""

                    table.add_row(lid, name, fav, status, count, scount, homepage,
                                  end_section=is_last_fav)

                self.console.print(table)
                self._print(f"[dim]共计 {len(items)} 位作者[/dim]")
            else:
                logger.info("还没有作者")

        if show_series:
            items = list_items("series")["items"]
            if items:
                table = Table(title="系列列表", show_lines=False)
                table.add_column("ID", justify="right", style="cyan", no_wrap=True)
                table.add_column("系列", style="bold")
                table.add_column("作者", style="green")
                table.add_column("作品数", justify="right", style="cyan")
                table.add_column("总赞数", justify="right", style="yellow")
                last = len(items) - 1
                for i, row in enumerate(items):
                    es = (i < last and row.get("author_name", "") != items[i+1].get("author_name", ""))
                    table.add_row(short_id(row.get("id", "")), row.get("name", ""),
                                  row.get("author_name", "") or "-",
                                  str(row.get("work_count", 0)),
                                  str(row.get("total_likes", 0)),
                                  end_section=es)
                self.console.print(table)
                self._print(f"[dim]共计 {len(items)} 个系列[/dim]")
            else:
                logger.info("还没有系列")

        if show_type:
            result = list_items("type")
            items = result["items"]
            if items:
                table = Table(title="分类统计", show_lines=False)
                table.add_column("分类名称", style="blue")
                table.add_column("作品数量", justify="right", style="cyan")
                for t, count in items.items():
                    table.add_row(t, str(count))
                self.console.print(table)
                self._print(f"[dim]共计 {len(items)} 种分类[/dim]")
            else:
                logger.info("还没有分类")

        return 0
