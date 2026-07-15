import argparse
from src.cli.core import BaseCommand
from src.operations import get_stats


class StatsCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        return "stats"

    @property
    def description(self) -> str:
        return "显示库的统计信息（总量、大小、分类分布、收藏、评分）"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace) -> int:
        stats = get_stats()

        if self._json_mode:
            return self._respond(True, data=stats)

        from rich.table import Table
        table = Table(title="库统计")
        table.add_column("指标", style="cyan")
        table.add_column("数值", style="green")
        table.add_row("作品总数", str(stats["total_books"]))
        table.add_row("作者数", str(stats["total_authors"]))
        table.add_row("系列数", str(stats["total_series"]))
        table.add_row("分类数", str(stats["total_types"]))
        table.add_row("收藏数量", str(stats["favorited_count"]))
        table.add_row("点赞数量", str(stats["liked_count"]))
        table.add_row("已评分数量", str(stats["rated_count"]))
        table.add_row("总大小", f"{stats['total_size_mb']} MB ({stats['total_size_kb']} KB)")
        self.console.print(table)

        id_type_count = stats.get("id_type_distribution", {})
        if id_type_count:
            id_table = Table(title="ID分布")
            id_table.add_column("类型", style="cyan")
            id_table.add_column("数量", justify="right", style="green")
            for t, count in sorted(id_type_count.items()):
                id_table.add_row(t, str(count))
            self.console.print(id_table)

        return 0
