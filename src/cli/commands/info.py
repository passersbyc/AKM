import argparse
from src.cli.core import BaseCommand
from src.core.logging import logger
from src.operations.info_op import get_info, get_related_works


class InfoCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "info"

    @property
    def description(self) -> str:
        return "查看作品/作者/系列完整元数据"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target_type", nargs="?", default="id",
                            help="资源类型 (book|author|series)，或直接给作品 ID")
        parser.add_argument("target", nargs="?", default=None,
                            help="ID/名称（指定了类型时需要）")
        parser.add_argument("-u", "--url", action="store_true", help="打开来源网址")
        parser.add_argument("-o", "--open", action="store_true", help="在关联软件中打开作品文件")

    def execute(self, args: argparse.Namespace) -> int:
        tt = args.target_type
        target = args.target
        if tt in ("book", "b", "author", "a", "series", "s"):
            if not target:
                if self._json_mode: return self._respond(False, error="请指定目标")
                logger.error("请指定目标"); return 1
        else:
            target = tt
            tt = "book"

        if tt in ("book", "b"):
            return self._show_book(target, args)
        elif tt in ("author", "a"):
            return self._show_author(target)
        elif tt in ("series", "s"):
            return self._show_series(target)
        return 1

    def _show_book(self, target: str, args: argparse.Namespace) -> int:
        book = get_info(target, "book")
        if not book:
            if self._json_mode: return self._respond(False, error=f"未找到ID: {target}")
            logger.error(f"未找到ID: {target}"); return 1

        if args.url:
            source = book.get("来源", "").strip()
            if source and source.startswith("http"):
                import webbrowser; webbrowser.open(source)
                logger.info(f"已打开: {source}")
            elif source == "local":
                logger.info("该作品为本地导入，无来源网址")
            else:
                logger.warning(f"来源不是有效网址: {source or '(空)'}")
        if args.open:
            from pathlib import Path; import subprocess
            fp = Path(book.get("文件路径", "").strip())
            if fp.exists():
                subprocess.run(["open", str(fp)])
                logger.info(f"已打开: {fp.name}")
            else:
                logger.warning(f"文件不存在: {fp}")

        if self._json_mode: return self._respond(True, data={"book": book})

        try:
            from rich.table import Table
            from rich.panel import Panel
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("字段", style="cyan", width=10, no_wrap=True)
            table.add_column("值", style="white", overflow="fold")
            table.add_row("ID", book.get("ID", ""))
            table.add_row("标题", book.get("标题", ""))
            table.add_row("作者", book.get("作者", "未知"))
            table.add_row("系列", book.get("系列", "-") or "-")
            table.add_row("标签", book.get("标签", "-") or "-")
            table.add_row("来源", book.get("来源", "-") or "-")
            table.add_row("分类", book.get("分类", "未知"))
            table.add_row("后缀", book.get("后缀", ""))
            table.add_row("文件大小", f"{book.get('文件大小(KB)', '0')} KB")
            table.add_row("MD5", book.get("MD5", ""))
            table.add_row("导入时间", book.get("导入时间", ""))
            table.add_row("收藏", "\u2665" if book.get("收藏", "否") == "是" else "")
            table.add_row("点赞", book.get("点赞", "0") if int(book.get("点赞", "0") or "0") > 0 else "")
            table.add_row("评分", book.get("评分", "-") if float(book.get("评分", "0") or "0") > 0 else "")
            table.add_row("文件路径", book.get("文件路径", ""))
            self.console.print(Panel(table, title=f"[bold green]{book.get('标题', '')}[/bold green]",
                                     subtitle=f"[dim]ID: {book.get('ID', '')}[/dim]"))
            desc = book.get("简介", "").strip()
            if desc:
                from rich.text import Text
                self.console.print(Panel(Text(desc), title="[bold]简介[/bold]"))

            series = book.get("系列", "").strip()
            if series:
                related = get_related_works(series, exclude_id=target)
                if related:
                    rel_table = Table(title=f"同系列推荐 ({series})")
                    rel_table.add_column("ID", style="dim", width=10)
                    rel_table.add_column("标题", style="green")
                    for r in related:
                        rel_table.add_row(r.get("ID", ""), r.get("标题", ""))
                    self.console.print(rel_table)
        except ImportError:
            logger.info(f"ID: {book.get('ID', '')}"); logger.info(f"标题: {book.get('标题', '')}")
            logger.info(f"作者: {book.get('作者', '未知')}"); logger.info(f"系列: {book.get('系列', '-')}")
        return 0

    def _show_author(self, target: str) -> int:
        result = get_info(target, "author")
        if not result:
            if self._json_mode: return self._respond(False, error=f"未找到作者: {target}")
            self._print_error(f"未找到作者: {target}"); return 1

        author = result["author"]
        works = result["works"]
        top_tags = result.get("top_tags", [])
        if self._json_mode:
            return self._respond(True, data={"author": author, "works": works, "top_tags": list(top_tags)})

        try:
            from rich.table import Table
            from rich.panel import Panel
            from rich.text import Text

            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("字段", style="cyan", width=10, no_wrap=True)
            table.add_column("值", style="white", overflow="fold")

            tid = author.get("id", "")
            name = author.get("name", "")
            status = author.get("follow_status", "")
            status_symbols = {"active": "◎ 正常", "paused": "⊘ 停止追更", "dead": "✕ 注销"}
            status_text = status_symbols.get(status, status)

            table.add_row("ID", tid)
            table.add_row("名称", name)
            table.add_row("状态", status_text)
            if author.get("pixiv_uid"):
                table.add_row("Pixiv UID", author["pixiv_uid"])
            if author.get("homepage"):
                table.add_row("主页", author["homepage"])
            if author.get("aliases"):
                table.add_row("曾用名", author["aliases"])
            if author.get("note"):
                table.add_row("备注", author["note"])
            if author.get("favorite"):
                table.add_row("收藏", "[red]\u2665[/red]")

            if top_tags:
                tag_text = ", ".join(f"{t}({c})" for t, c in top_tags)
                table.add_row("热门标签", tag_text)

            table.add_row("作品数", str(len(works)))
            if works:
                series_set = set()
                for w in works:
                    s = w.get("系列", "")
                    if s:
                        series_set.add(s)
                table.add_row("系列数", str(len(series_set)))

            self.console.print(Panel(table, title=f"[bold green]{name}[/bold green]",
                                     subtitle=f"[dim]ID: {tid}  |  作品: {len(works)}[/dim]"))

            if works:
                from rich.table import Table as RTable
                from src.core.database import short_id

                top_works = sorted(works, key=lambda w: int(w.get("点赞", "0") or "0"), reverse=True)[:10]
                work_table = RTable(title=f"热度 Top {len(top_works)}（共 {len(works)} 个作品）", show_lines=False)
                work_table.add_column("ID", style="dim", width=10)
                work_table.add_column("标题", style="green")
                work_table.add_column("赞", style="yellow", justify="right", width=6)
                for w in top_works:
                    likes = w.get("点赞", "0") or "0"
                    work_table.add_row(short_id(w.get("ID", "")), w.get("标题", ""),
                                       likes if int(likes) > 0 else "")
                self.console.print(work_table)

                recent_works = sorted(works, key=lambda w: w.get("导入时间", ""), reverse=True)[:5]
                recent_table = RTable(title=f"最近 {len(recent_works)} 个作品", show_lines=False)
                recent_table.add_column("ID", style="dim", width=10)
                recent_table.add_column("标题", style="green")
                recent_table.add_column("时间", style="dim", width=10)
                for w in recent_works:
                    dt = (w.get("导入时间", "") or "")[:10]
                    recent_table.add_row(short_id(w.get("ID", "")), w.get("标题", ""), dt)
                self.console.print(recent_table)
        except ImportError:
            self._print_info(f"\n[bold]{author.get('name', '')}[/bold]  [{author.get('follow_status', '')}]")
            self._print_info(f"  ID:       {author.get('id', '')}")
            self._print_info(f"  Pixiv UID:{author.get('pixiv_uid', '')}")
            self._print_info(f"  主页:     {author.get('homepage', '')}")
            if author.get("favorite"):
                self._print_info(f"  收藏:     是")
            if top_tags:
                self._print_info(f"  热门标签: {', '.join(f'{t}({c})' for t, c in top_tags)}")
            if works:
                from src.core.database import short_id
                top_works = sorted(works, key=lambda w: int(w.get("点赞", "0") or "0"), reverse=True)[:10]
                self._print_info(f"\n  [bold]热度 Top {len(top_works)}（共 {len(works)} 个作品）:[/bold]")
                for w in top_works:
                    likes = w.get("点赞", "0") or "0"
                    l = f"  ♥{likes}" if int(likes) > 0 else ""
                    self._print_info(f"    {short_id(w.get('ID', ''))}  {w.get('标题')}  {l}")

                recent_works = sorted(works, key=lambda w: w.get("导入时间", ""), reverse=True)[:5]
                self._print_info(f"\n  [bold]最近 {len(recent_works)} 个作品:[/bold]")
                for w in recent_works:
                    dt = (w.get("导入时间", "") or "")[:10]
                    self._print_info(f"    {short_id(w.get('ID', ''))}  {w.get('标题')}  {dt}")
        return 0

    def _show_series(self, name: str) -> int:
        result = get_info(name, "series")
        if not result:
            if self._json_mode: return self._respond(False, error=f"未找到系列: {name}")
            self._print_error(f"未找到系列: {name}"); return 1

        series = result["series"]
        works = result["works"]
        author_name = result.get("author_name", "")
        if self._json_mode: return self._respond(True, data=result)

        self._print_info(f"\n[bold]{name}[/bold]")
        self._print_info(f"  作者:     {author_name}")
        self._print_info(f"  ID:       {series.get('id', '')}")
        if works:
            self._print_info(f"\n  [bold]作品列表 ({len(works)} 个):[/bold]")
            for w in works:
                self._print_info(f"    {w.get('ID')}  {w.get('标题')}")
        return 0
