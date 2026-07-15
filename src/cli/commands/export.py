import argparse
from pathlib import Path

from src.cli.core import BaseCommand
from src.operations import export_by_query


class ExportCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "export"

    @property
    def description(self) -> str:
        return "将指定作者或标签的所有作品导出到目录，支持系列 EPUB/PDF 合并"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("query", help="要导出的目标名称（默认按作者），或以空格分隔的标签关键词")
        parser.add_argument("destination", nargs="?", default=".", help="导出目标路径（默认当前目录）")
        parser.add_argument("-n", "--name", type=str, help="自定义导出文件夹名称")
        parser.add_argument("-t", "--tag", action="store_true", help="按标签导出而不是按作者导出")
        parser.add_argument("-c", "--type", type=str, help="按分类筛选 (如 小说, 漫画)")
        parser.add_argument("-l", "--number", type=int, help="按点赞量限制导出数量")
        parser.add_argument("-i", "--id", type=str, help="按作者本地ID批量导出（逗号分隔）")
        parser.add_argument("-f", "--favorited", action="store_true", help="仅导出收藏作者的作品")
        parser.add_argument("--format", default="folder", choices=["zip", "folder", "epub", "completeness"],
                            help="导出格式，zip 为压缩包，folder 为文件夹，epub 为 EPUB 电子书，completeness 为按分类全局合并 (默认: folder)")

    def execute(self, args: argparse.Namespace) -> int:
        dest_dir = Path(args.destination or ".").resolve()
        if not dest_dir.exists():
            try:
                dest_dir.mkdir(parents=True)
            except Exception as e:
                return self._respond(False, error=f"无法创建目标目录: {e}")

        author_ids = [x.strip() for x in (args.id or "").split(",") if x.strip()]
        if author_ids or args.favorited:
            mode = "id"
        elif args.tag:
            mode = "tag"
        else:
            mode = "author"

        query = args.query
        export_name = args.name if args.name else query.replace(" ", "_")
        result = export_by_query(
            query=query,
            dest_dir=dest_dir,
            export_name=export_name,
            mode=mode,
            filter_type=getattr(args, 'type', None),
            limit=args.number or 0,
            output_format=getattr(args, 'format', 'folder'),
            author_ids=author_ids,
            favorited_only=args.favorited,
        )

        if not result["success"]:
            return self._respond(False, error=result.get("error") or "导出失败")

        if getattr(args, 'format', 'folder') == "completeness":
            merged_list = [(ft, r) for ft, r in (result.get("results") or {}).items()
                          if r.get("status") == "merged"]
            if not self._json_mode and merged_list:
                self._print(f"[bold bright_green]━━━ 按分类全局合并 ━━━[/bold bright_green]")
                for ft, r in merged_list:
                    output_path = r.get("output", "")
                    count = r.get("count", 0)
                    safe_out = str(output_path).replace(str(Path(result.get("destination", ""))), ".", 1) if output_path else ""
                    self._print(f"  [bold cyan]{ft:　<4s}[/bold cyan] [bright_green]{safe_out}[/bright_green] [bold yellow]{count} 文件[/bold yellow]")
                self._print()

            if self._json_mode:
                return self._respond(True, {
                    "exported": result["exported"],
                    "destination": result["destination"],
                    "results": result["results"],
                })
            return 0

        fmt_label = "EPUB 电子书" if getattr(args, 'format', 'folder') == "epub" else ("文件夹" if getattr(args, 'format', 'folder') == "folder" else "文件")
        self._print(f"[bold green]✓[/bold green] 导出完成: [bold cyan]{fmt_label}[/bold cyan] [bright_green]{result['destination']}[/bright_green] [bold yellow]({result['exported']} 项)[/bold yellow]")

        if self._json_mode:
            return self._respond(True, {
                "exported": result["exported"],
                "destination": result["destination"],
            })
        return 0
