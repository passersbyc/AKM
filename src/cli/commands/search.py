import argparse
from src.cli.core import BaseCommand
from src.operations import search_works
from src.core.logging import logger
from src.core.database import short_id
from rich.table import Table


class SearchCommand(BaseCommand):
    def __init__(self) -> None:
        super().__init__()

    @property
    def description(self) -> str:
        return "搜索库中的文件，支持多字段筛选和正则表达式"

    @property
    def name(self) -> str:
        return "search"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("query", type=str, nargs="?", help="搜索的标题关键词")
        parser.add_argument("-a", "--author", type=str, help="作者名称")
        parser.add_argument("-s", "--series", type=str, help="系列名称")
        parser.add_argument("-t", "--type", type=str, help="分类名称")
        parser.add_argument("-g", "--tag", type=str, help="标签关键词")
        parser.add_argument("-o", "--source", type=str, help="来源关键词")
        parser.add_argument("-k", "--keyword", type=str, help="在所有字段中搜索关键词")
        parser.add_argument("--id-prefix", type=str, help="按ID前缀筛选（如 n0101 查找作者01的所有作品）")
        parser.add_argument("--liked", choices=["yes", "no"], help="按点赞状态筛选")
        parser.add_argument("--regex", action="store_true", help="使用正则表达式匹配")
        parser.add_argument("--limit", type=int, default=0, help="限制输出数量")
        parser.add_argument("--favorited", choices=["yes", "no"], help="按收藏状态筛选")

    def execute(self, args: argparse.Namespace) -> int:
        if not any([args.query, args.author, args.series, args.type, args.tag, args.source, args.keyword, args.favorited, args.id_prefix, args.liked]):
            return self._respond(False, error="请输入搜索条件")

        items = search_works(
            query=args.query or "",
            author=args.author or "",
            series=args.series or "",
            file_type=args.type or "",
            tags=args.tag or "",
            source=args.source or "",
            keyword=args.keyword or "",
            regex=args.regex,
            limit=args.limit,
            favorited=args.favorited or "",
            id_prefix=args.id_prefix or "",
            liked=args.liked or "",
        )
        total = len(items)

        if self._json_mode:
            return self._respond(True, {"total": total, "items": items})

        if not items:
            self.console.print("[yellow]什么都没有找到[/yellow]")
            return 0

        self.console.print(f"[cyan]找到 {total} 个结果：[/cyan]")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("ID", width=10)
        table.add_column("标题", style="green")
        table.add_column("作者", style="blue")
        table.add_column("分类", style="yellow")
        table.add_column("收藏", style="red")
        table.add_column("点赞", style="yellow")
        table.add_column("评分", style="cyan")
        table.add_column("来源", justify="left")

        id_list = []
        for row in items:
            file_id = row.get('ID', 'N/A')
            if file_id != 'N/A':
                id_list.append(file_id)
            table.add_row(
                short_id(str(file_id)), row.get('标题', ''),
                row.get('作者', '未知'), row.get('分类', '') or '未知',
                row.get('收藏', '否') == '是' and "♥" or "",
                row.get('点赞', '0') if int(row.get('点赞', '0') or '0') > 0 else "",
                row.get('评分', '-') if float(row.get('评分', '0') or '0') > 0 else "",
                row.get('来源', '')
            )

        self.console.print(table)
        if id_list:
            self.console.print(f"[bold cyan]结果 ID:[/bold cyan] {', '.join(id_list)}")
        return 0
