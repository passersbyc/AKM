import argparse
import json
from pathlib import Path

from src.cli.base import BaseCommand
from src.core.config import get_project_root


def _get_export_defaults():
    config_path = get_project_root() / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    ps = cfg.get("project_settings", {})
    return {
        "dest": ps.get("export_path", "."),
        "format": ps.get("export_format", "folder"),
    }


class ExportCommand(BaseCommand):
    verb = "export"
    nouns = ["author", "mylikeauthor", "mylikeworks"]
    description = "导出作品到指定目录"

    def configure_parser(self, parser: argparse.ArgumentParser) -> None:
        defaults = _get_export_defaults()
        parser.add_argument("target", nargs="?", default=None,
                            help="作品 ID 或名称")
        parser.add_argument("dest", nargs="?", default=defaults["dest"],
                            help="导出目标路径")
        parser.add_argument("--format", default=defaults["format"],
                            choices=["folder", "zip", "epub"],
                            help="导出格式")

    def configure_noun_parser(self, parser: argparse.ArgumentParser,
                               noun: str) -> None:
        defaults = _get_export_defaults()
        if noun == "author":
            parser.add_argument("target", type=str, help="作者 ID 或名称")
            parser.add_argument("dest", nargs="?", default=defaults["dest"],
                                help="导出目标路径")
            parser.add_argument("--format", default=defaults["format"],
                                choices=["folder", "zip", "epub"])
            parser.add_argument("--type", type=str, help="按分类筛选")
            parser.add_argument("--number", type=int, default=0,
                                help="按点赞量限制数量")
        elif noun in ("mylikeauthor", "mylikeworks"):
            parser.add_argument("dest", nargs="?", default=defaults["dest"],
                                help="导出目标路径")
            parser.add_argument("--format", default=defaults["format"],
                                choices=["folder", "zip", "epub"])
            parser.add_argument("--type", type=str, help="按分类筛选")
            parser.add_argument("--number", type=int, default=0,
                                help="按点赞量限制数量")

    def execute(self, args: argparse.Namespace, noun=None) -> int:
        if noun == "author":
            return self._export_author(args)
        elif noun == "mylikeauthor":
            return self._export_mylikeauthor(args)
        elif noun == "mylikeworks":
            return self._export_mylikeworks(args)
        else:
            return self._export_work(args)

    # ── helpers ────────────────────────────────────────────

    def _resolve_dest(self, dest_str: str) -> Path:
        dest_dir = Path(dest_str).resolve()
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.output.error(f"无法创建目标目录: {e}")
            return None
        return dest_dir

    def _print_result(self, result: dict, fmt_label: str) -> int:
        if not result["success"]:
            self.output.info(f"导出失败: {result.get('error', '未知错误')}")
            return 1
        dest = result.get("destination", "")
        try:
            dest = str(Path(dest).relative_to(Path.cwd()))
        except ValueError:
            pass
        self.output.info(f"[green]导出完成:[/green] {fmt_label} "
                         f"[bright_green]{dest}[/bright_green] "
                         f"[yellow]({result['exported']} 项)[/yellow]")
        return 0

    # ── export <work> ──────────────────────────────────────

    def _export_work(self, args: argparse.Namespace) -> int:
        if not args.target:
            self.output.info("用法: export <作品ID或名称> [导出路径]")
            return 1
        dest_dir = self._resolve_dest(args.dest)
        if dest_dir is None:
            return 1

        from src.operations.export_op import export_work
        fmt = getattr(args, 'format', 'folder')
        result = export_work(args.target, dest_dir, output_format=fmt)
        fmt_label = {"folder": "文件夹", "zip": "压缩包", "epub": "EPUB"}.get(fmt, fmt)
        return self._print_result(result, fmt_label)

    # ── export author ──────────────────────────────────────

    def _export_author(self, args: argparse.Namespace) -> int:
        if not args.target:
            self.output.info("用法: export author <作者ID或名称> [导出路径]")
            return 1
        dest_dir = self._resolve_dest(args.dest)
        if dest_dir is None:
            return 1

        from src.operations.export_op import export_author
        result = export_author(
            args.target, dest_dir,
            filter_type=getattr(args, 'type', None),
            limit=getattr(args, 'number', 0),
            output_format=getattr(args, 'format', 'folder'),
        )
        fmt_label = {"folder": "文件夹", "zip": "压缩包", "epub": "EPUB"}.get(
            getattr(args, 'format', 'folder'), 'folder')
        return self._print_result(result, fmt_label)

    # ── export mylikeauthor ────────────────────────────────

    def _export_mylikeauthor(self, args: argparse.Namespace) -> int:
        dest_dir = self._resolve_dest(args.dest)
        if dest_dir is None:
            return 1

        from src.operations.export_op import export_mylikeauthor
        result = export_mylikeauthor(
            dest_dir,
            filter_type=getattr(args, 'type', None),
            limit=getattr(args, 'number', 0),
            output_format=getattr(args, 'format', 'folder'),
        )
        fmt_label = {"folder": "文件夹", "zip": "压缩包", "epub": "EPUB"}.get(
            getattr(args, 'format', 'folder'), 'folder')
        return self._print_result(result, fmt_label)

    # ── export mylikeworks ─────────────────────────────────

    def _export_mylikeworks(self, args: argparse.Namespace) -> int:
        dest_dir = self._resolve_dest(args.dest)
        if dest_dir is None:
            return 1

        from src.operations.export_op import export_mylikeworks
        result = export_mylikeworks(
            dest_dir,
            output_format=getattr(args, 'format', 'folder'),
        )
        fmt_label = {"folder": "文件夹", "zip": "压缩包", "epub": "EPUB"}.get(
            getattr(args, 'format', 'folder'), 'folder')
        return self._print_result(result, fmt_label)
