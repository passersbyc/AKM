import argparse
from src.cli.core import BaseCommand
from src.operations import verify_integrity


class VerifyCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "verify"

    @property
    def description(self) -> str:
        return "校验作品文件完整性（支持单本或全部扫描）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("book_id", type=str, nargs="?", help="要校验的作品ID（不指定则扫描全部）")

    def execute(self, args: argparse.Namespace) -> int:
        result = verify_integrity(args.book_id)

        if self._json_mode:
            return self._respond(True, data=result)

        if args.book_id:
            if result.get("error"):
                self._print_error(result["error"])
                return 1
            status = "完整" if result["valid"] else "损坏/不完整"
            self._print_info(f"[{result['id']}] {result.get('name', '')} - {status}")
        else:
            from rich.table import Table
            table = Table(title="完整性校验")
            table.add_column("ID", style="dim", width=14)
            table.add_column("标题", style="green")
            table.add_column("状态", style="cyan")
            for item in result["items"]:
                status = "[green]完整" if item["valid"] else "[red]损坏" if item["exists"] else "[yellow]文件缺失"
                table.add_row(item["id"], item["name"], status)
            self.console.print(table)
            self.console.print(f"总计: {result['total']} | 完整: [green]{result['valid_count']}[/green] | 异常: [red]{result['total'] - result['valid_count']}[/red]")

        return 0
