import argparse

from src.cli.base import BaseCommand
from src.core.logging import logger
from src.operations import get_info, get_related_works


class InfoCommand(BaseCommand):
    verb = "info"
    nouns = ["work"]
    description = "查看作品完整元数据"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        if noun != "work":
            return
        parser.add_argument("target", type=str, help="作品 ID")
        parser.add_argument("-u", "--url", action="store_true", help="打开来源网址")
        parser.add_argument("-o", "--open", action="store_true", help="在关联软件中打开作品文件")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun != "work":
            return self.output.result(False, error="info 仅支持 work")
        target = args.target
        book = get_info(target, "book")
        if not book:
            return self.output.result(False, error=f"未找到ID: {target}")

        if getattr(args, "url", False):
            source = book.get("来源", "").strip()
            if source and source.startswith("http"):
                import webbrowser
                webbrowser.open(source)
                logger.info(f"已打开: {source}")
            elif source == "local":
                logger.info("该作品为本地导入，无来源网址")
            else:
                logger.warning(f"来源不是有效网址: {source or '(空)'}")

        if getattr(args, "open", False):
            from pathlib import Path
            import subprocess
            fp = Path(book.get("文件路径", "").strip())
            if fp.exists():
                subprocess.run(["open", str(fp)])
                logger.info(f"已打开: {fp.name}")
                self._record_open(target, book.get("标题", ""))
            else:
                logger.warning(f"文件不存在: {fp}")

        if self.output.json_mode:
            return self.output.result(True, data={"book": book})

        try:
            from rich.table import Table
            from rich.panel import Panel
            from rich.text import Text
            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("字段", style="cyan", width=10, no_wrap=True)
            table.add_column("值", style="white", overflow="fold")
            for k, v in [
                ("ID", book.get("ID", "")),
                ("标题", book.get("标题", "")),
                ("作者", book.get("作者", "未知")),
                ("系列", book.get("系列", "-") or "-"),
                ("标签", book.get("标签", "-") or "-"),
                ("来源", book.get("来源", "-") or "-"),
                ("分类", book.get("分类", "未知")),
                ("后缀", book.get("后缀", "")),
                ("文件大小", f"{book.get('文件大小(KB)', '0')} KB"),
                ("MD5", book.get("MD5", "")),
                ("导入时间", book.get("导入时间", "")),
                ("收藏", "♥" if book.get("收藏", "否") == "是" else ""),
            ]:
                table.add_row(k, str(v))
            likes = book.get("点赞", "0") or "0"
            rating = book.get("评分", "-") or "0"
            table.add_row("点赞", likes if int(likes) > 0 else "")
            table.add_row("评分", rating if float(rating) > 0 else "")
            table.add_row("文件路径", book.get("文件路径", ""))
            self.console.print(Panel(
                table,
                title=f"[bold green]{book.get('标题', '')}[/bold green]",
                subtitle=f"[dim]ID: {book.get('ID', '')}[/dim]",
            ))
            desc = book.get("简介", "").strip()
            if desc:
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
            logger.info(f"ID: {book.get('ID', '')}")
            logger.info(f"标题: {book.get('标题', '')}")
        return 0

    def _record_open(self, work_id: str, title: str) -> None:
        try:
            from src.core.database import get_db
            db = get_db()
            db.execute(
                "INSERT INTO recent_opens (work_id, title) VALUES (?, ?)",
                (work_id, title),
            )
            db.execute(
                "DELETE FROM recent_opens WHERE id NOT IN "
                "(SELECT id FROM recent_opens ORDER BY opened_at DESC LIMIT 50)"
            )
            db.commit()
        except Exception:
            pass
