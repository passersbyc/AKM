import argparse

from src.cli.base import BaseCommand
from src.operations.matcher import resolve_work, resolve_author
from src.core.database import short_id
from src.core.logging import logger
from src.operations import delete_book, delete_by_ids, delete_authors
from src.operations.delete_op import resolve_author_targets


class DeleteCommand(BaseCommand):
    verb = "delete"
    nouns = ["author", "all"]
    description = "删除作品或作者，或清空库"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("target", type=str, nargs="?", help="作品 ID 或名称")
        parser.add_argument("--yes", "-y", action="store_true", help="跳过确认")

    def configure_noun_parser(self, parser: argparse.ArgumentParser, noun: str) -> None:
        if noun == "author":
            parser.add_argument("target", type=str, help="作者 ID 或名称")
            parser.add_argument("--yes", "-y", action="store_true", help="跳过确认")
        elif noun == "all":
            parser.add_argument("--yes", "-y", action="store_true", help="跳过确认")
            parser.add_argument("--keep-tables", action="store_true",
                                help="保留作者/系列/计数器表")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun == "author":
            return self._delete_author(args)
        if noun == "all":
            return self._delete_all(args)
        return self._delete_work(args)

    def _delete_work(self, args: argparse.Namespace) -> int:
        if not args.target:
            return self.output.result(False, error="请指定要删除的作品 ID 或名称")

        work = resolve_work(args.target, self.output)
        if not work:
            return self.output.result(False, error=f"未找到作品: {args.target}")

        wid = work["id"]
        title = work.get("title", "")

        if not self.output.json_mode and not (args.yes or self.output.no_confirm):
            self.output.info(f"将删除: [cyan]{short_id(wid)}[/cyan] {title}")
            if not self.output.confirm("确认删除？"):
                self.output.info("[dim]已取消[/dim]")
                return 0

        result = delete_book({wid}, keep_file=False, clear_tables=False)
        if self.output.json_mode:
            return self.output.result(True, data=result)
        self.output.info(f"[green]✓[/green] 已删除: {title}")
        return 0

    def _delete_author(self, args: argparse.Namespace) -> int:
        author = resolve_author(args.target, self.output)
        if not author:
            return self.output.result(False, error=f"未找到作者: {args.target}")

        aid = author["id"]
        name = author.get("name", "")

        if not self.output.json_mode and not (args.yes or self.output.no_confirm):
            self.output.info(f"将删除作者: [cyan]{aid}[/cyan] {name} 及其全部作品")
            if not self.output.confirm("确认删除？"):
                self.output.info("[dim]已取消[/dim]")
                return 0

        deleted, _ = delete_authors([aid])
        if self.output.json_mode:
            return self.output.result(True, data={"deleted": deleted, "id": aid})
        self.output.info(f"[green]✓[/green] 已删除作者: {name}（{deleted} 部作品）")
        return 0

    def _delete_all(self, args: argparse.Namespace) -> int:
        if not self.output.json_mode and not (args.yes or self.output.no_confirm):
            self.output.info("[yellow]⚠ 将清空整个作品库[/yellow]")
            if not self.output.confirm("确认清空？此操作不可撤销"):
                self.output.info("[dim]已取消[/dim]")
                return 0

        from src.core.database import get_db
        db = get_db()
        rows = db.execute("SELECT id FROM works").fetchall()
        ids = {r["id"] for r in rows}
        result = delete_book(ids, keep_file=False, clear_tables=not args.keep_tables)
        if self.output.json_mode:
            return self.output.result(True, data=result)
        self.output.info(f"[green]✓[/green] 已清空库: 删除 {result['deleted']} 部作品")
        return 0
